"""Legacy PDF signature (``/adbe.x509.rsa_sha1``) verification — the pre-CMS/PKCS#7 Adobe method.

Several Indian government e-registration / e-Sign portals (commonly pre-~2016 deployments — observed
in the wild on Tamil Nadu Registration Department encumbrance certificates) still produce this raw
RSASSA-PKCS1-v1_5(SHA-1) signature instead of modern PAdES/CMS. It is a genuinely different container
format, not a malformed document: ``/Contents`` holds a bare RSA signature (no ASN.1 ``SignedData``
wrapper at all), computed directly over the ``/ByteRange``-covered bytes, with the signer's certificate
in ``/Cert`` (no embedded chain — unlike CMS, which typically carries the whole chain).

pyHanko's ``PdfFileReader.embedded_signatures`` parses every ``/Contents`` as a CMS ``ContentInfo`` and
raises on this sub-filter (ASN.1 tag mismatch) — not a document defect on our end, a container format
pyHanko's CMS-only pipeline doesn't speak. This module reads the signature field directly via pikepdf
and performs REAL cryptographic verification (never a stub): recomputes the exact covered digest and
checks the embedded certificate's RSA signature, then reuses the same pinned-anchor + point-in-time
chain logic as the CMS path (verification/signature.py) via :func:`validate_chain_with_point_in_time`.

Honest bound: SHA-1 is cryptographically weaker than the SHA-256 the modern PAdES/CMS path uses — that
is inherent to this legacy format (the original signer chose it years before we saw the document), not
something we chose; callers should not treat a rsa_sha1 verification as equivalent-strength evidence to
a fresh PAdES-SHA256 one, only as equally *honest* about what it actually establishes.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

RSA_SHA1_SUB_FILTER = "adbe.x509.rsa_sha1"

_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([+\-Z])(\d{2})?'?(\d{2})?'?)?"
)


def _parse_pdf_date(raw: str) -> datetime | None:
    """Parse a PDF date string (``D:YYYYMMDDHHmmSSOHH'mm'``, ISO 32000 §7.9.4) to an aware datetime.

    Used for a legacy signature's ``/M`` (the signing tool's claimed modification time) — a plain PDF
    dict entry, but one that sits alongside ``/Contents`` in the SAME ``/ByteRange``-covered bytes, so
    it cannot be altered without invalidating the RSA signature (as tamper-evident as the rest of the
    signed content, even though the format predates a dedicated signed 'signing-time' attribute).
    Returns ``None`` on anything that doesn't match — never guesses a time.
    """
    m = _PDF_DATE_RE.match(raw)
    if not m:
        return None
    year, month, day, hour, minute, second, tz_sign, tz_hh, tz_mm = m.groups()
    try:
        dt = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
        )
    except ValueError:
        return None
    if tz_sign in ("+", "-"):
        offset = timedelta(hours=int(tz_hh or 0), minutes=int(tz_mm or 0))
        if tz_sign == "-":
            offset = -offset
        return dt.replace(tzinfo=timezone(offset))
    return dt.replace(tzinfo=UTC)


def extract_signature_fields(file_bytes: bytes) -> list[dict[str, Any]]:
    """Enumerate every ``/V`` signature dictionary in the PDF's AcroForm via pikepdf.

    Deliberately not pyHanko (see module docstring). Returns one dict per signature field —
    ``sub_filter``, ``byte_range``, ``contents`` (raw signature bytes), ``certs`` (list of DER-encoded
    certificate bytes, leaf first, empty if none embedded). Never raises: an unopenable PDF or an
    individual malformed field yields fewer results, not a crash (CLAUDE.md §4 — a scan step must not
    take down the whole analysis).
    """
    import pikepdf

    fields: list[dict[str, Any]] = []
    try:
        pdf = pikepdf.open(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 — an unparsable PDF yields no fields, never a crash
        logger.warning("legacy signature scan: could not open PDF: %r", exc)
        return fields
    try:
        acroform = pdf.Root.get("/AcroForm")
        if acroform is None or "/Fields" not in acroform:
            return fields
        for f in acroform.Fields:
            v = f.get("/V")
            if v is None or "/Filter" not in v:
                continue
            try:
                byte_range = [int(x) for x in v["/ByteRange"]]
                contents = bytes(v["/Contents"])
                cert_obj = v.get("/Cert")
                if cert_obj is None:
                    certs: list[bytes] = []
                else:
                    try:
                        certs = [bytes(c) for c in cert_obj]
                    except TypeError:
                        certs = [bytes(cert_obj)]
                m_raw = v.get("/M")
                signing_time = _parse_pdf_date(str(m_raw)) if m_raw is not None else None
                fields.append(
                    {
                        "sub_filter": str(v.get("/SubFilter", "")).lstrip("/"),
                        "byte_range": byte_range,
                        "contents": contents,
                        "certs": certs,
                        "signing_time": signing_time,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — one malformed field must not drop the others
                logger.warning("legacy signature scan: could not read a signature field: %r", exc)
    finally:
        pdf.close()
    return fields


def _unwrap_octet_string(data: bytes) -> bytes:
    """Some signing tools store the raw RSA signature DER-wrapped in an OCTET STRING (observed:
    ``04 82 01 00 <256 bytes>`` ahead of a 2048-bit-key signature) instead of storing it bare. Parse it
    as one via asn1crypto and return the unwrapped payload; if it isn't a valid OCTET STRING (the
    ordinary case — a genuinely bare signature), return the bytes unchanged. Never guesses: a
    successful parse is definitive either way.
    """
    from asn1crypto import core

    try:
        parsed = core.OctetString.load(data)
        payload = parsed.native
        # A valid parse must consume the ENTIRE input — a signature that merely happens to start with
        # byte 0x04 is not actually DER-wrapped, and re-encoding must round-trip exactly.
        if isinstance(payload, bytes) and parsed.dump() == data:
            return payload
    except Exception:  # noqa: BLE001 — any parse failure means "not wrapped", not an error
        pass
    return data


def verify_rsa_sha1(file_bytes: bytes, field: dict[str, Any]) -> dict[str, Any]:
    """Verify one ``/adbe.x509.rsa_sha1`` signature field against the document's real bytes.

    Returns ``{"intact", "valid", "covers_whole_file", "certificate" (asn1crypto Certificate or None),
    "error"}`` — shaped so the caller can fold it into the same verified/tampered logic as the CMS path.
    ``intact``/``valid`` are both exactly the RSA-PKCS1v15-SHA1 math result: this format carries no
    separate signed-attributes structure to distinguish "digest matched" from "signature validated" the
    way CMS does — the single check covers both.
    """
    from asn1crypto import x509 as asn1_x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    byte_range = field["byte_range"]
    if len(byte_range) != 4:
        return {
            "intact": False, "valid": False, "covers_whole_file": False, "certificate": None,
            "error": f"unexpected /ByteRange shape: {byte_range}",
        }
    off1, len1, off2, len2 = byte_range
    covered = file_bytes[off1 : off1 + len1] + file_bytes[off2 : off2 + len2]
    covers_whole = off1 == 0 and (off2 + len2) == len(file_bytes)

    certs = field["certs"]
    if not certs:
        return {
            "intact": False, "valid": False, "covers_whole_file": covers_whole, "certificate": None,
            "error": "no /Cert embedded — cannot verify",
        }

    try:
        leaf = asn1_x509.Certificate.load(certs[0])
        pubkey = serialization.load_der_public_key(leaf.public_key.dump())
    except Exception as exc:  # noqa: BLE001 — a malformed embedded cert fails closed, never crashes
        return {
            "intact": False, "valid": False, "covers_whole_file": covers_whole, "certificate": None,
            "error": f"could not parse embedded certificate: {exc!r}",
        }

    if not isinstance(pubkey, rsa.RSAPublicKey):
        return {
            "intact": False, "valid": False, "covers_whole_file": covers_whole, "certificate": leaf,
            "error": "embedded certificate's key is not RSA — unsupported for adbe.x509.rsa_sha1",
        }

    # Some signing tools wrap the raw RSA signature in a DER OCTET STRING (observed: a
    # `04 82 01 00 <256 bytes>` header before a 2048-bit-key signature) rather than storing it bare —
    # unwrap it if present so the payload handed to verify() is the actual signature, not a DER header
    # plus signature (which would never verify and would misreport a genuine document as tampered).
    signature_bytes = _unwrap_octet_string(field["contents"])

    try:
        pubkey.verify(signature_bytes, covered, padding.PKCS1v15(), hashes.SHA1())
        math_ok = True
    except InvalidSignature:
        math_ok = False

    return {
        "intact": math_ok,
        "valid": math_ok,
        "covers_whole_file": covers_whole,
        "certificate": leaf,
        "error": None,
    }


def validate_chain_with_point_in_time(
    leaf: Any,
    *,
    trust_roots: list[Any],
    crls: list[Any],
    revocation_mode: str,
    signing_time: datetime | None,
) -> tuple[bool, bool]:
    """Chain ``leaf`` (no intermediates available for this legacy format) to a pinned root.

    Tries "now" first; if that fails and a signing time is available, retries as of that historical
    moment with ``retroactive_revinfo`` — the same short-lived-certificate rescue used by the CMS path
    (verification/signature.py), reused here so both signature formats treat an expired-by-review-time
    cert identically. Returns ``(trusted, point_in_time_used)``.
    """
    from pyhanko_certvalidator import CertificateValidator, ValidationContext

    vc = ValidationContext(
        trust_roots=trust_roots, crls=crls, allow_fetching=False, revocation_mode=revocation_mode
    )
    try:
        asyncio.run(CertificateValidator(leaf, validation_context=vc).async_validate_path())
        return True, False
    except Exception as exc:  # noqa: BLE001 — chain failure of any kind falls through to the retry
        logger.info("legacy signature: chain validation (now) failed: %r", exc)

    if signing_time is None:
        return False, False
    try:
        retry_vc = ValidationContext(
            trust_roots=trust_roots,
            crls=crls,
            allow_fetching=False,
            revocation_mode=revocation_mode,
            moment=signing_time,
            retroactive_revinfo=True,
        )
        asyncio.run(CertificateValidator(leaf, validation_context=retry_vc).async_validate_path())
        return True, True
    except Exception as exc:  # noqa: BLE001 — a failed retry just means untrusted, never a crash
        logger.info("legacy signature: point-in-time chain retry failed: %r", exc)
        return False, False
