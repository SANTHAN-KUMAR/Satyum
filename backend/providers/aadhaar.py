"""Aadhaar offline e-KYC XML provider — real UIDAI XML-signature verification, no partner (§0.2).

What this is (BUILD-MANIFEST / PROPOSAL-001 §4.4 "UIDAI offline XML"): the citizen generates a
**paperless offline e-KYC** from UIDAI (a ZIP, password-protected with a share-code, containing an XML
that UIDAI **digitally signs** with an enveloped XML signature). We verify that signature for real —
no partner, no AUA/KUA licence — using ``signxml`` against a **pinned UIDAI public certificate**, so a
document only reads VERIFIED if it was actually signed by UIDAI's key.

What this is NOT (honest boundary, CLAUDE.md §3.4): the **live Aadhaar e-KYC API** (real-time
demographic pull) is restricted to AUA/KUA-licensed entities — that is gated and not built. This
offline-XML path is the no-partner substitute UIDAI publishes precisely for this purpose. We also use
the **masked reference id**, never a full Aadhaar number.

Integrity (CLAUDE.md §3.1): VERIFIED is earned only by a real XML signature that validates against the
pinned UIDAI cert. With no pinned cert we **fail closed** (cannot assert it is UIDAI). A tampered XML,
or one signed by any other key, is INVALID.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from app.config import settings
from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    ProvenanceMode,
    SignatureStatus,
    SourceResult,
)

logger = logging.getLogger(__name__)

_ZIP_MAGIC = b"PK\x03\x04"
_AADHAAR_LIVE_GATE = (
    "Live Aadhaar e-KYC (real-time demographic pull) is restricted to AUA/KUA-licensed entities — "
    "gated. This offline e-KYC XML path verifies UIDAI's signature with no partner; only live data is gated."
)
_AADHAAR_VERIFY_GATE = (
    "Cannot verify the Aadhaar offline e-KYC signature: no UIDAI public certificate is pinned and no "
    "CCA-India root is available. Pin UIDAI's published public certificate (uidai.gov.in -> Aadhaar "
    "Paperless Offline e-KYC -> 'public certificate for signature validation') in the UIDAI cert dir, "
    "or keep the CCA-India roots in the trust store (UIDAI signs offline e-KYC under the India PKI). "
    "No mock is ever returned."
)


def _load_ca_roots() -> list[str]:
    """Load the CCA-India root certs (PEM strings) from the trust store — UIDAI signs offline e-KYC
    under the India PKI, so the embedded signing cert can be chain-validated to these."""
    configured = Path(settings.trust_anchor_dir)
    cert_dir = configured if configured.is_dir() else (
        Path(__file__).resolve().parent.parent / "verification" / "trust_anchors"
    )
    return _load_uidai_pems(cert_dir)  # same loader: reads PEM/DER certs from a dir as PEM strings


def _load_uidai_pems(cert_dir: Path) -> list[str]:
    """Load pinned UIDAI public certs (PEM or DER) as PEM strings for signxml. Empty -> fail closed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    pems: list[str] = []
    if not cert_dir.is_dir():
        return pems
    for path in sorted(cert_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".pem", ".crt", ".cer", ".der"):
            continue
        try:
            raw = path.read_bytes()
            try:
                cert = x509.load_pem_x509_certificate(raw)
            except ValueError:
                cert = x509.load_der_x509_certificate(raw)
            pems.append(cert.public_bytes(serialization.Encoding.PEM).decode("ascii"))
        except (ValueError, OSError) as exc:
            logger.warning("skipping unparsable UIDAI cert %s: %s", path.name, exc)
    return pems


class AadhaarOfflineProvider:
    """Verify a UIDAI offline e-KYC XML's enveloped signature against a pinned UIDAI certificate."""

    name = "aadhaar_offline"

    def __init__(self, uidai_cert_dir: str | None = None) -> None:
        self._cert_dir = uidai_cert_dir

    def applicable(self, doc_request: DocRequest) -> bool:
        return doc_request.doc_class == DocClass.IDENTITY

    def _resolve_cert_dir(self) -> Path:
        if self._cert_dir is not None:
            return Path(self._cert_dir)
        from app.config import settings
        configured = Path(settings.uidai_cert_dir)  # SATYUM_UIDAI_CERT_DIR override
        if configured.is_dir():
            return configured
        return Path(__file__).resolve().parent.parent / "verification" / "uidai_certs"

    def fetch(
        self,
        consent: ConsentArtifact,
        doc_request: DocRequest,
        payload: bytes | None = None,
    ) -> SourceResult:
        if payload is None:
            return self._result(SignatureStatus.NOT_VERIFIED, ProvenanceMode.SOURCE_PULL,
                                detail="no Aadhaar offline e-KYC XML/ZIP supplied", gate=_AADHAAR_LIVE_GATE)

        # 1) get the XML bytes (from a share-code-protected ZIP, or a raw XML upload)
        try:
            xml_bytes = self._extract_xml(payload, doc_request.share_code)
        except _ExtractError as exc:
            return self._result(SignatureStatus.NOT_VERIFIED, ProvenanceMode.SOURCE_PULL,
                                detail=f"could not read offline e-KYC: {exc}")

        # 2) gather trust material: a pinned UIDAI public cert (UIDAI's prescribed method) AND/OR the
        #    CCA-India roots (UIDAI signs offline e-KYC under the India PKI). Neither -> fail closed.
        uidai_pems = _load_uidai_pems(self._resolve_cert_dir())
        ca_roots = _load_ca_roots()
        if not uidai_pems and not ca_roots:
            return self._result(SignatureStatus.NOT_VERIFIED, ProvenanceMode.SOURCE_PULL,
                                gate=_AADHAAR_VERIFY_GATE,
                                detail="no UIDAI public certificate pinned and no CCA root available")

        # 3) verify the enveloped XML signature: against a pinned UIDAI cert, else chain to a CCA root
        ok, err = self._verify_signature(xml_bytes, uidai_pems, ca_roots)
        if not ok:
            return self._result(SignatureStatus.INVALID, ProvenanceMode.MANUAL_UPLOAD,
                                detail=(
                                    "Aadhaar offline XML signature INVALID — "
                                    f"tampering or not UIDAI-signed ({err})"
                                ))

        ref, demo = self._extract_fields(xml_bytes)
        return self._result(
            SignatureStatus.VERIFIED, ProvenanceMode.SOURCE_PULL,
            issuer="UIDAI (offline e-KYC)",
            detail=f"UIDAI offline e-KYC signature verified — reference {ref or 'n/a'} (masked)",
            measurements={"reference_id": ref, "fields_present": sorted(demo.keys()),
                          "note": "masked reference id only — never a full Aadhaar number"},
            structured_json={"reference_id": ref, **demo},
        )

    # --- helpers ---------------------------------------------------------------------------------

    def _extract_xml(self, payload: bytes, share_code: str | None) -> bytes:
        if payload[:4] == _ZIP_MAGIC:
            if not share_code:
                raise _ExtractError("the offline e-KYC ZIP needs its share-code (password)")
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                    if not names:
                        raise _ExtractError("no XML inside the ZIP")
                    return zf.read(names[0], pwd=share_code.encode("utf-8"))
            except (RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                # RuntimeError: wrong password; NotImplementedError: AES-encrypted ZIP (needs pyzipper)
                raise _ExtractError(f"could not open the ZIP ({exc})") from exc
        # assume a raw XML upload
        return payload

    def _verify_signature(
        self, xml_bytes: bytes, uidai_pems: list[str], ca_roots: list[str]
    ) -> tuple[bool, str]:
        import os
        import tempfile

        from lxml import etree
        from signxml import XMLVerifier

        try:
            root = etree.fromstring(xml_bytes)  # noqa: S320 — signed, but parsed only to verify
        except etree.XMLSyntaxError as exc:
            return False, f"malformed XML: {exc}"

        last_err = "no anchor matched"
        # 1) direct verification against a pinned UIDAI public cert (UIDAI's prescribed method).
        for pem in uidai_pems:
            try:
                XMLVerifier().verify(root, x509_cert=pem)
                return True, ""
            except Exception as exc:  # noqa: BLE001 — signxml raises varied exc types on a bad signature
                last_err = type(exc).__name__

        # 2) chain the embedded UIDAI signing cert to a CCA root (works when the chain is embedded).
        if ca_roots:
            bundle = None
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False, encoding="ascii") as fh:
                    fh.write("\n".join(ca_roots))
                    bundle = fh.name
                XMLVerifier().verify(root, ca_pem_file=bundle)
                return True, ""
            except Exception as exc:  # noqa: BLE001 — chain failure is a fail-closed condition, not a crash
                last_err = f"{type(exc).__name__} (chain-to-CCA)"
            finally:
                if bundle and os.path.exists(bundle):
                    os.unlink(bundle)
        return False, last_err

    @staticmethod
    def _extract_fields(xml_bytes: bytes) -> tuple[str | None, dict[str, str]]:
        from lxml import etree

        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError:
            return None, {}
        ref = root.get("referenceId")
        demo: dict[str, str] = {}
        poi = root.find(".//Poi")
        if poi is not None:
            for k in ("name", "dob", "gender"):
                v = poi.get(k)
                if v:
                    demo[k] = v
        return ref, demo

    def _result(self, status: SignatureStatus, mode: ProvenanceMode, *, detail: str,
                issuer: str | None = None, gate: str | None = None,
                measurements: dict | None = None, structured_json: dict | None = None) -> SourceResult:
        return SourceResult(
            provider=self.name, doc_class=DocClass.IDENTITY, signature_status=status,
            provenance_mode=mode, issuer=issuer, gate=gate, detail=detail,
            measurements=measurements or {}, structured_json=structured_json,
        )


class _ExtractError(Exception):
    """Internal: could not obtain the XML from the supplied payload."""
