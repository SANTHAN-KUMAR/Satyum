"""Tier-1 cryptographic provenance: PAdES/CMS (PDF) and C2PA (image) signature verification.

This is the **cyber core** of Satyum (CLAUDE.md §1/§10, ADR-002): before we trust a document's
bytes we verify its *cryptographic* origin and integrity. "A signature exists" is **not** "the
signature is valid" — the defended attack classes (BUILD-MANIFEST, TESTING-STRATEGY §3 Tier-1) are:

  * an attacker signing with **their own / a self-signed cert** — the CMS math is intact but the
    chain does **not** reach a pinned trust anchor  → *tampered* (forged origin);
  * **bytes appended after** the signed ``/ByteRange`` (incremental-update / shadow attack) — the
    digest still matches the covered bytes but the signature no longer covers the *whole file*
    → *tampered* (post-signing modification);
  * a broken digest (any edit inside the covered range) → *tampered*;
  * **no signature at all** → *absent* → ``NOT_EVALUATED`` (routes to the Tier-2 forensic path;
    never an auto-pass — absence is not innocence).

We verify the full chain to a **pinned** trust root (the public anchors shipped in
``settings.trust_anchor_dir``; in production the CCA-India PKI root that DigiLocker / signed bank
e-statements chain to) and require the signature to cover the entire file. Fail-closed: any internal
failure becomes an ``ERROR`` signal, never a silent pass.

Honest bound (ADR-002, TESTING-STRATEGY §3): provenance proves **origin + integrity**, not
*truthfulness* — a genuinely-signed statement from a real fraudster is "verified source", not a
fraud verdict. Absence of a signature is routed to forensics, not treated as a pass.

Two analyzers, both Tier-1 / ``Mode.FILE``:
  * :class:`PadesSignatureAnalyzer`  — PAdES/CMS on PDFs (pyHanko), order 10.
  * :class:`C2paProvenanceAnalyzer`  — C2PA content credentials on images (c2pa SDK), order 11.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

logger = logging.getLogger(__name__)

# --- Start: asn1crypto monkey-patch for malformed Indian Gov PDFs ---
# Indian Gov portals (TNREGINET, IGRS) generate CMS signatures where strict ASN.1
# 'constructed' sequences are encoded as 'primitive'. We patch asn1crypto to retry
# and force the 'constructed' bit on primitive parse failures.
import asn1crypto.core

_orig_build = asn1crypto.core._build

def _lenient_build(*args, **kwargs):
    args_list = list(args)
    # If method is 0 (primitive), but could be a malformed constructed type
    if len(args_list) > 1 and args_list[1] == 0:
        try:
            return _orig_build(*args, **kwargs)
        except ValueError as e:
            if "method should have been constructed, but primitive was found" in str(e):
                args_list[1] = 1  # force constructed
                return _orig_build(*args_list, **kwargs)
            raise
    return _orig_build(*args, **kwargs)

asn1crypto.core._build = _lenient_build
# --- End: asn1crypto monkey-patch ---

# Provenance states surfaced in measurements['provenance'] (shared vocabulary with the UI/Provenance).
PROV_VERIFIED = "verified"  # intact + chains to a pinned anchor + covers the whole file + not revoked
PROV_TAMPERED = "tampered"  # present but INVALID: appended bytes / bad digest / revoked cert
PROV_ABSENT = "absent"  # no signature at all -> route to Tier 2
# Signature is cryptographically intact + valid + covers the whole file + not revoked, but its chain
# does NOT reach a pinned anchor. The document is UNALTERED — this is NOT tampering. It means the
# issuer cannot be confirmed (e.g. a genuine UIDAI/CCA-India-signed Aadhaar when those roots are not
# pinned). Treated as "no confirmed source" -> forensic fallback, never a fabricated tamper verdict.
PROV_UNVERIFIED_ISSUER = "unverified_issuer"

# v2 provenance result contract (ADR-004 Layer 1) — the states surfaced to the decision brain.
# SOURCE_AVOIDED is emitted by the PDF-only red-flag analyzer (provenance.py), not here.
PROV_RESULT_VERIFIED = "VERIFIED_SOURCE"
PROV_RESULT_TAMPERED = "TAMPERED"
PROV_RESULT_NO_SOURCE = "NO_SOURCE"

# Suspicion is the binary cyber-fact: a verified chain is clean (0.0); an invalid one is active
# tampering evidence (1.0). There is no "somewhat signed" — a chain either reaches the anchor or not.
SUSPICION_VERIFIED = 0.0
SUSPICION_TAMPERED = 1.0

# Weight: Tier-1 provenance is the first-line control. When it speaks (verified/tampered) it is
# dispositive, so it carries full weight; ADR-002. DEFAULT — needs calibration against the corpus.
PROVENANCE_WEIGHT = 1.0

_PDF_MAGIC = b"%PDF-"


def _resolve_anchor_dir(override: str | None) -> Path:
    """Resolve the trust-anchor directory.

    ``settings.trust_anchor_dir`` is repo-relative ("backend/verification/trust_anchors"); resolve
    it whether the process runs from the repo root or from ``backend/``.
    """
    if override is not None:
        return Path(override)
    configured = Path(settings.trust_anchor_dir)
    if configured.is_dir():
        return configured
    # Fall back to the path relative to this file (…/backend/verification/trust_anchors).
    here = Path(__file__).resolve().parent / "trust_anchors"
    return here


def _load_trust_roots(anchor_dir: Path) -> list[Any]:
    """Load every PEM/DER certificate in ``anchor_dir`` as an asn1crypto x509.Certificate.

    Returns ``[]`` if the directory is missing or empty — the caller treats "no pinned anchors" as
    a fail-closed condition (we cannot assert trust against an empty trust store).
    """
    from pyhanko.keys import load_cert_from_pemder  # local import: heavy crypto dep

    roots: list[Any] = []
    if not anchor_dir.is_dir():
        return roots
    for path in sorted(anchor_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".pem", ".crt", ".cer", ".der"):
            continue
        try:
            roots.append(load_cert_from_pemder(str(path)))
        except (ValueError, OSError) as exc:
            # A malformed anchor must not silently shrink the trust store unnoticed.
            logger.warning("skipping unparsable trust anchor %s: %s", path.name, exc)
    return roots


def _load_crls(anchor_dir: Path) -> list[Any]:
    """Load every ``.crl`` in ``anchor_dir`` and its ``crls/`` subdir as asn1crypto CertificateLists.

    Offline revocation: production fetches CRL/OCSP online (``settings.signature_allow_fetching``), but
    an air-gapped / test deployment can pin CRLs next to the anchors — e.g. the CCA-India CRL published
    alongside the root. DER and PEM-wrapped CRLs are both accepted; a malformed CRL is skipped with a
    warning (it must never silently shrink the revocation evidence).
    """
    from asn1crypto import crl as asn1_crl
    from asn1crypto import pem

    crls: list[Any] = []
    for d in (anchor_dir, anchor_dir / "crls"):
        if not d.is_dir():
            continue
        for path in sorted(d.iterdir()):
            if not path.is_file() or path.suffix.lower() != ".crl":
                continue
            try:
                data = path.read_bytes()
                if data.lstrip().startswith(b"-----BEGIN"):
                    _, _, data = pem.unarmor(data)
                crls.append(asn1_crl.CertificateList.load(data))
            except (ValueError, OSError) as exc:
                logger.warning("skipping unparsable CRL %s: %s", path.name, exc)
    return crls


def _cms_signing_time(emb: Any) -> Any:
    """The CMS 'signing-time' SIGNED attribute (RFC 5652 §11.3), read directly from the embedded
    signature's ``SignerInfo`` — independent of whether certificate-chain validation succeeds.

    It is a *signed* attribute: covered by the same digest computation the signature's ``intact``
    check verifies, so an attacker cannot alter this claimed time without invalidating the whole
    signature. This makes it a legitimate (if not TSA-independent) basis for point-in-time certificate
    validation when no embedded RFC3161 timestamp is present. Returns ``None`` if absent or malformed
    — never fabricates a time.
    """
    try:
        signed_attrs = emb.signed_data["signer_infos"][0]["signed_attrs"]
    except (KeyError, IndexError, TypeError):
        return None
    if signed_attrs.native is None:
        return None
    for attr in signed_attrs:
        try:
            if attr["type"].native == "signing_time":
                return attr["values"][0].native
        except (KeyError, IndexError, ValueError):
            continue
    return None


def _timestamp_info(status: Any) -> dict[str, Any] | None:
    """Project a signature's embedded RFC3161 timestamp validity to a JSON-safe dict, or ``None``.

    ``status.timestamp_validity`` is a ``TimestampSignatureStatus`` when the signature carries a
    trusted-timestamp token (PAdES-T and above), else ``None``. We surface the asserted signing *time*
    and whether that token itself is intact / valid / chains to a pinned TSA root — so the evidence
    pack can show "signed at <time>, timestamp authority trusted".
    """
    tv = getattr(status, "timestamp_validity", None)
    if tv is None:
        return None
    ts = getattr(tv, "timestamp", None)
    return {
        "time": ts.isoformat() if ts is not None else None,
        "intact": bool(getattr(tv, "intact", False)),
        "valid": bool(getattr(tv, "valid", False)),
        "trusted": bool(getattr(tv, "trusted", False)),
    }


def _cn(name: Any) -> str | None:
    """Extract the common_name from an asn1crypto x509.Name, defensively (best-effort, never fatal)."""
    try:
        native = name.native  # OrderedDict of relative distinguished names
    except Exception:  # noqa: BLE001 — metadata extraction must never break verification
        return None
    if not isinstance(native, dict):
        return None
    cn = native.get("common_name")
    if isinstance(cn, list):
        return str(cn[0]) if cn else None
    return str(cn) if cn is not None else None


def _signer_identity(emb: Any, status: Any | None) -> dict[str, str | None]:
    """Best-effort signer subject/issuer CN from the validation status or the embedded signature.

    This is metadata for the "issued by X" trust badge ONLY — it never affects the verdict, which is
    the chain-to-anchor decision. Any failure yields ``None`` values. The exact pyHanko attribute
    (``status.signing_cert`` vs ``emb.signer_cert``) is probed defensively so a version difference
    degrades to "issuer unknown", never an error.
    """
    cert = None
    candidates = []
    if status is not None:
        candidates.append(lambda: status.signing_cert)
    candidates.append(lambda: emb.signer_cert)
    for getter in candidates:
        try:
            c = getter()
        except Exception:  # noqa: BLE001 — probe; missing attribute is expected on some versions
            continue
        if c is not None:
            cert = c
            break
    if cert is None:
        return {"subject_cn": None, "issuer_cn": None}
    return {
        "subject_cn": _cn(getattr(cert, "subject", None)),
        "issuer_cn": _cn(getattr(cert, "issuer", None)),
    }


class PadesSignatureAnalyzer:
    """Verify embedded PAdES/CMS signatures on a PDF, chaining to a pinned trust anchor.

    Approach (BUILD-MANIFEST `BUILD_REAL_WORKS`): open the bytes with pyHanko's ``PdfFileReader``;
    for every ``EmbeddedPdfSignature`` run ``validate_pdf_signature`` against a
    ``ValidationContext(trust_roots=[...])`` built from the pinned anchors. A signature only counts
    as *verified* when it is cryptographically **intact**, its chain is **trusted** (reaches a
    pinned root), **and** its coverage is the **entire file** (so appended-bytes / shadow attacks
    are caught). Any present-but-failing condition is *tampered*. No signature is *absent*.
    """

    name = "pades_signature"
    layer = 1
    mode = Mode.FILE
    order = 10

    def __init__(
        self,
        anchor_dir: str | None = None,
        *,
        revocation_mode: str | None = None,
        allow_fetching: bool | None = None,
    ) -> None:
        # Configurable so tests can pin a self-generated test CA as the trust root and exercise an
        # explicit revocation policy (§5 config-over-hardcode). Defaults come from settings: production
        # sets allow_fetching=True + revocation_mode="hard-fail" for online CRL/OCSP, the strict posture.
        self._anchor_dir_override = anchor_dir
        self._revocation_mode = (
            revocation_mode if revocation_mode is not None else settings.signature_revocation_mode
        )
        self._allow_fetching = (
            allow_fetching if allow_fetching is not None else settings.signature_allow_fetching
        )

    def applicable(self, ctx: AnalysisContext) -> bool:
        if ctx.intake_mode != Mode.FILE or not ctx.file_bytes:
            return False
        # Cheap structural gate: only run the PDF path on something that looks like a PDF.
        head = ctx.file_bytes[:1024]
        return _PDF_MAGIC in head[:8] or _PDF_MAGIC in head

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if not ctx.file_bytes:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, "no file bytes to verify")
        try:
            return self._analyze(ctx)
        except Exception as exc:  # noqa: BLE001 — fail-closed boundary (§4); never crash the verdict
            logger.exception("PAdES verification raised unexpectedly")
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"signature verification failed: {exc!r}"
            )

    def _analyze(self, ctx: AnalysisContext) -> LayerSignal:
        import io

        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import SignatureCoverageLevel, validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
        from pyhanko_certvalidator.errors import PathValidationError

        try:
            from pyhanko_certvalidator.errors import RevokedError
        except ImportError:  # older certvalidator: fall back to message-based revocation detection
            RevokedError = ()  # type: ignore[assignment]  # isinstance(x, ()) is always False

        anchor_dir = _resolve_anchor_dir(self._anchor_dir_override)
        trust_roots = _load_trust_roots(anchor_dir)
        if not trust_roots:
            # Fail-closed (§10): with no pinned anchors we cannot assert a chain — never auto-pass.
            return LayerSignal.error(
                self.name,
                self.layer,
                self.mode,
                f"no pinned trust anchors loaded from {anchor_dir} — cannot verify chain",
            )

        crls = _load_crls(anchor_dir)

        try:
            reader = PdfFileReader(io.BytesIO(ctx.file_bytes), strict=False)
            # Encrypted (password-protected) PDF: decrypt IN MEMORY with the applicant-supplied password
            # so the ORIGINAL signed bytes are read unmodified. This is what preserves the signature — a
            # 3rd-party "remove password" tool re-saves the file and destroys the /ByteRange coverage
            # (CLAUDE.md §10; verification/pdf_crypto.py). No password for an encrypted doc -> the API
            # gates to NEEDS_PASSWORD upstream and this analyzer never runs.
            if reader.encrypted:
                if not ctx.pdf_password:
                    return LayerSignal.not_evaluated(
                        self.name, self.layer, self.mode,
                        "PDF is password-protected — password required to verify the signature",
                    )
                reader.decrypt(ctx.pdf_password)
            embedded = list(reader.embedded_signatures)
        except Exception as exc:  # noqa: BLE001 — malformed PDF is ordinary bad input, fail-closed
            # pyHanko parses every /Contents as a CMS ContentInfo and raises on the legacy
            # /adbe.x509.rsa_sha1 sub-filter some (esp. older Indian govt e-registration) portals still
            # use — a different container format, not a malformed document. Try that real verification
            # path before giving up (never let "we don't speak this container" masquerade as "unparsable
            # garbage" when it's actually a well-understood, verifiable legacy format).
            legacy_signal = self._analyze_legacy_rsa_sha1(ctx, trust_roots, crls)
            if legacy_signal is not None:
                return legacy_signal
            logger.warning("could not parse PDF for signature extraction: %r", exc)
            return LayerSignal.error(self.name, self.layer, self.mode, f"unparsable PDF: {exc!r}")

        if not embedded:
            # Absent -> NOT_EVALUATED: route to Tier 2 forensics. Absence is never an auto-pass.
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "no embedded PAdES/CMS signature — routing to forensic fallback",
                provenance=PROV_ABSENT,
                provenance_result=PROV_RESULT_NO_SOURCE,
                method="PAdES",
            )

        # Real revocation: production fetches CRL/OCSP from the certificate's endpoints
        # (settings.signature_allow_fetching=True); offline / air-gapped deployments pin CRLs next to
        # the anchors (<anchor_dir>/crls). revocation_mode is the certvalidator policy (§10).
        vc = ValidationContext(
            trust_roots=trust_roots,
            crls=crls,
            allow_fetching=self._allow_fetching,
            revocation_mode=self._revocation_mode,
        )
        # Embedded RFC3161 timestamps validate against their own context (the TSA chains to a pinned
        # root); revocation is kept soft for the TSA so a timestamp revinfo gap never hard-fails an
        # otherwise-valid document signature.
        ts_vc = ValidationContext(
            trust_roots=trust_roots,
            crls=crls,
            allow_fetching=self._allow_fetching,
            revocation_mode="soft-fail",
        )

        # Evaluate every signature; the document is only verified if ALL present signatures verify
        # and at least one covers the whole file. Any failing / under-covering / revoked signature is
        # tampering evidence.
        per_sig: list[dict[str, Any]] = []
        all_verified = True
        whole_file_covered = False

        for idx, emb in enumerate(embedded):
            revoked = False
            ts_info: dict[str, Any] | None = None
            srdt: Any = None
            # Read the CMS 'signing-time' SIGNED attribute (RFC 5652 §11.3) directly, independently of
            # whether path validation below succeeds — it is a *signed* attribute (covered by the same
            # digest we verify as intact), so it is exactly as tamper-evident as the rest of the
            # signature, regardless of what the certificate-chain outcome turns out to be.
            independent_signing_time = _cms_signing_time(emb)
            try:
                status = validate_pdf_signature(
                    emb,
                    signer_validation_context=vc,
                    ts_validation_context=ts_vc,
                )
                intact = bool(status.intact)
                valid = bool(status.valid)
                trusted = bool(status.trusted)
                coverage = status.coverage
                # Under soft-fail a revoked cert surfaces here (no exception): it was checked against
                # the CRL/OCSP and found revoked. Under hard-fail it raises instead (handled below).
                revoked = bool(getattr(status, "revoked", False))
                ts_info = _timestamp_info(status)
                srdt = getattr(status, "signer_reported_dt", None) or independent_signing_time
            except PathValidationError as exc:
                # Chain failed to reach a pinned anchor (attacker / self-signed cert) OR — under
                # hard-fail revocation — the cert is revoked (RevokedError is a PathValidationError) OR
                # the cert's validity WINDOW has since passed (handled by the point-in-time retry below).
                revoked = isinstance(exc, RevokedError) or "revoked" in str(exc).lower()
                logger.info("signature %d path validation failed (revoked=%s): %s", idx, revoked, exc)
                intact = valid = trusted = False
                coverage = SignatureCoverageLevel.UNCLEAR
                srdt = independent_signing_time
            except Exception as exc:  # noqa: BLE001 — a per-signature failure must not pass-through
                if type(exc).__name__ == "SignatureValidationError" and (
                    "recognized SubFilter type" in str(exc)
                ):
                    # A genuinely different, unrecognized signature container (e.g. the real-world
                    # /adbe.pkcs7.sha1 variant) — not a corrupt document. Route to forensic fallback,
                    # never a fabricated "tampered" verdict for a format gap (§3.1).
                    logger.warning("signature %d uses unsupported subfilter: %r", idx, exc)
                    return LayerSignal.not_evaluated(
                        self.name,
                        self.layer,
                        self.mode,
                        f"signature uses an unsupported format ({exc!s}) — routing to forensic fallback",
                        provenance=PROV_ABSENT,
                        provenance_result=PROV_RESULT_NO_SOURCE,
                        method="PAdES",
                    )
                logger.warning("signature %d validation raised: %r", idx, exc)
                intact = valid = trusted = False
                coverage = SignatureCoverageLevel.UNCLEAR
                srdt = independent_signing_time

            covers_whole = coverage == SignatureCoverageLevel.ENTIRE_FILE

            # Point-in-time retry: rescues a signature made with a genuinely short-lived certificate —
            # a real, common pattern for Indian govt e-Sign (Aadhaar eSign / Protean / DigiLocker issue
            # certs valid for only ~30 minutes, scoped to one signing act) which will look "expired" to
            # any validation performed after the fact, even though it was completely valid when signed.
            # Safe by construction: `moment` only changes the certificate's validity-PERIOD check; it
            # cannot change which root a chain resolves to, so an attacker/self-signed/wrong-issuer
            # chain fails identically at any moment — this can only rescue an otherwise-legitimate,
            # correctly-pinned chain, never launder an untrusted one (CLAUDE.md §3.1).
            point_in_time_validated = False
            if not trusted and intact and valid and covers_whole and not revoked and srdt is not None:
                try:
                    # moment= cannot combine with allow_fetching=True (pyhanko_certvalidator); revocation
                    # evidence for a point-in-time check must come from the pinned CRLs, never a live
                    # fetch keyed to "now". retroactive_revinfo=True: a CRL published AFTER the signing
                    # moment is still valid evidence that the cert was NOT revoked at that moment (CRLs
                    # only ever add revocations, they don't retract them) — required here because a
                    # short-lived cert's own real-time CRL cannot have existed yet at signing time.
                    retry_vc = ValidationContext(
                        trust_roots=trust_roots,
                        crls=crls,
                        allow_fetching=False,
                        revocation_mode=self._revocation_mode,
                        moment=srdt,
                        retroactive_revinfo=True,
                    )
                    retry_status = validate_pdf_signature(
                        emb, signer_validation_context=retry_vc, ts_validation_context=ts_vc
                    )
                    if retry_status.trusted and retry_status.intact and retry_status.valid:
                        trusted = True
                        point_in_time_validated = True
                except Exception as exc:  # noqa: BLE001 — a failed retry just keeps the original result
                    logger.info("signature %d point-in-time retry failed: %r", idx, exc)

            signer_time = srdt.isoformat() if srdt is not None else None
            sig_verified = intact and valid and trusted and covers_whole and not revoked
            all_verified = all_verified and sig_verified
            whole_file_covered = whole_file_covered or covers_whole

            per_sig.append(
                {
                    "index": idx,
                    "intact": intact,  # digest matches the covered bytes
                    "valid": valid,  # CMS/PKCS#7 math validates
                    "trusted": trusted,  # chain reaches a pinned anchor
                    "covers_whole_file": covers_whole,  # no appended bytes after /ByteRange
                    "coverage": coverage.name if coverage is not None else "NONE",
                    "revoked": revoked,  # CRL/OCSP says the signing certificate is revoked
                    "timestamp": ts_info,  # embedded RFC3161 timestamp validity (or None)
                    "signer_reported_time": signer_time,
                    # True iff trust was only established by re-checking the chain as of the signed
                    # signing-time attribute, not "now" — the cert had since expired (short-lived
                    # e-Sign cert), but was genuinely valid, chained, and unrevoked at the time it signed.
                    "point_in_time_validation": point_in_time_validated,
                }
            )

        verified = all_verified and whole_file_covered
        measurements: dict[str, Any] = {
            "provenance": PROV_VERIFIED if verified else PROV_TAMPERED,
            "provenance_result": PROV_RESULT_VERIFIED if verified else PROV_RESULT_TAMPERED,
            "method": "PAdES",
            "signature_count": len(embedded),
            "anchors_pinned": len(trust_roots),
            "crls_loaded": len(crls),
            "revocation_mode": self._revocation_mode,
            "online_revocation": self._allow_fetching,
            "signatures": per_sig,
        }

        if verified:
            # Source-of-truth answered at the PKI root: publish for downstream analyzers / red-flag.
            ctx.shared["provenance_verified"] = True
            # Best-effort signer identity for the "issued by X" trust badge (metadata only — never the
            # verdict). Consumed by providers/digilocker.py for the DigiLocker issuer label.
            identity = _signer_identity(embedded[0], None)
            ctx.shared["signer_identity"] = {
                "subject_cn": identity["subject_cn"],
                "issuer_cn": identity["issuer_cn"],
            }
            measurements["signer_subject_cn"] = identity["subject_cn"]
            measurements["signer_issuer_cn"] = identity["issuer_cn"]
            ts0 = per_sig[0].get("timestamp")
            ts_note = f"; RFC3161 timestamp validated ({ts0['time']})" if ts0 and ts0.get("trusted") else ""
            if not ts_note and any(s.get("point_in_time_validation") for s in per_sig):
                # No RFC3161 timestamp, but the chain was confirmed valid AS OF the signed CMS
                # signing-time attribute — the common short-lived-cert e-Sign pattern (§ above).
                signed_at = per_sig[0]["signer_reported_time"]
                ts_note = f"; certificate had since expired but was valid when signed ({signed_at})"
            return LayerSignal.valid(
                self.name,
                self.layer,
                self.mode,
                SUSPICION_VERIFIED,
                PROVENANCE_WEIGHT,
                "PAdES signature verified: intact, chains to a pinned trust anchor, covers the whole "
                f"file, certificate not revoked{ts_note}",
                measurements=measurements,
            )

        # Carve-out — "valid signature, untrusted issuer" is NOT tampering (CLAUDE.md §3.1/§3.3).
        # When EVERY signature is cryptographically intact + valid, covers the whole file, and is not
        # revoked — and the ONLY failure is that the chain does not reach a pinned anchor — the document
        # is UNALTERED. This is a genuine, common case: a real UIDAI/CCA-India-signed Aadhaar or signed
        # bank e-statement whose issuer root we have not pinned. Reporting it as "tampering" and hard-
        # rejecting it is a false fraud accusation. Treat it as "source not confirmed" → forensic
        # fallback (like an unsigned doc), never a fabricated tamper verdict. (A self-signed forgery,
        # by contrast, raises PathValidationError above and lands as intact=False → genuine tamper, so
        # it is NOT excused here.) Pin the issuer's root (e.g. CCA-India) to verify such a doc at source.
        content_intact_all = all(
            s["intact"] and s["valid"] and s["covers_whole_file"] and not s["revoked"]
            for s in per_sig
        )
        if content_intact_all:
            untrusted_idx = [s["index"] for s in per_sig if not s["trusted"]]
            measurements["provenance"] = PROV_UNVERIFIED_ISSUER
            measurements["provenance_result"] = PROV_RESULT_NO_SOURCE
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "signature is cryptographically valid and the document is unaltered, but the signer's "
                f"certificate does not chain to a pinned trust anchor (sig {untrusted_idx}) — issuer "
                "not confirmed. Routing to forensic verification; pin the issuer root (e.g. CCA-India) "
                "to verify this document at source.",
                **measurements,
            )

        # Present and genuinely INVALID: broken digest, appended bytes after /ByteRange, or a revoked
        # certificate — the signed content was altered or the cert was revoked. This IS tampering.
        reasons = []
        for s in per_sig:
            if s["revoked"]:
                reasons.append(f"sig {s['index']}: signing certificate is REVOKED (CRL/OCSP)")
            elif not s["intact"] or not s["valid"]:
                reasons.append(f"sig {s['index']}: cryptographic digest/signature invalid")
            elif not s["covers_whole_file"]:
                reasons.append(
                    f"sig {s['index']}: bytes appended after /ByteRange (coverage={s['coverage']})"
                )
            elif not s["trusted"]:
                reasons.append(f"sig {s['index']}: chain does not reach a pinned anchor")
        detail = "; ".join(reasons) or "signature present but did not verify"
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            SUSPICION_TAMPERED,
            PROVENANCE_WEIGHT,
            f"PAdES signature INVALID — tampering evidence ({detail})",
            measurements=measurements,
        )

    def _analyze_legacy_rsa_sha1(
        self, ctx: AnalysisContext, trust_roots: list[Any], crls: list[Any]
    ) -> LayerSignal | None:
        """Real verification for the legacy ``/adbe.x509.rsa_sha1`` PDF signature format — see
        ``verification/legacy_pdf_signature.py`` for why pyHanko's CMS-only parser raises on it.

        Returns ``None`` if the PDF carries no such signature field at all — the caller then falls
        back to the original "unparsable PDF" error, unchanged, for a genuinely broken/unknown PDF.
        """
        from verification.legacy_pdf_signature import (
            RSA_SHA1_SUB_FILTER,
            extract_signature_fields,
            validate_chain_with_point_in_time,
            verify_rsa_sha1,
        )

        if ctx.file_bytes is None:
            return None

        fields = [
            f for f in extract_signature_fields(ctx.file_bytes) if f["sub_filter"] == RSA_SHA1_SUB_FILTER
        ]
        if not fields:
            return None  # some OTHER parse failure — not this legacy format; let the caller error out

        per_sig: list[dict[str, Any]] = []
        all_verified = True
        whole_file_covered = False
        leaf_certs: list[Any] = []

        for idx, field in enumerate(fields):
            result = verify_rsa_sha1(ctx.file_bytes, field)
            intact = valid = bool(result["intact"])
            covers_whole = bool(result["covers_whole_file"])
            leaf = result["certificate"]
            trusted = False
            point_in_time_validated = False
            if leaf is not None and intact:
                trusted, point_in_time_validated = validate_chain_with_point_in_time(
                    leaf,
                    trust_roots=trust_roots,
                    crls=crls,
                    revocation_mode=self._revocation_mode,
                    signing_time=field.get("signing_time"),
                )
            if leaf is not None:
                leaf_certs.append(leaf)

            sig_verified = intact and valid and trusted and covers_whole
            all_verified = all_verified and sig_verified
            whole_file_covered = whole_file_covered or covers_whole

            per_sig.append(
                {
                    "index": idx,
                    "intact": intact,
                    "valid": valid,
                    "trusted": trusted,
                    "covers_whole_file": covers_whole,
                    "coverage": "ENTIRE_FILE" if covers_whole else "PARTIAL",
                    "revoked": False,  # not independently tracked for this format (module docstring)
                    "timestamp": None,  # no RFC3161 timestamp mechanism in this legacy format
                    "signer_reported_time": (
                        field["signing_time"].isoformat() if field.get("signing_time") else None
                    ),
                    "point_in_time_validation": point_in_time_validated,
                    "error": result.get("error"),
                }
            )

        verified = all_verified and whole_file_covered
        measurements: dict[str, Any] = {
            "provenance": PROV_VERIFIED if verified else PROV_TAMPERED,
            "provenance_result": PROV_RESULT_VERIFIED if verified else PROV_RESULT_TAMPERED,
            "method": "legacy_rsa_sha1",
            "signature_count": len(fields),
            "anchors_pinned": len(trust_roots),
            "crls_loaded": len(crls),
            "revocation_mode": self._revocation_mode,
            "online_revocation": False,  # moment-based retry never allows live fetching
            "signatures": per_sig,
        }

        if verified:
            ctx.shared["provenance_verified"] = True
            leaf = leaf_certs[0] if leaf_certs else None
            subject_cn = issuer_cn = None
            if leaf is not None:
                try:
                    subject_cn = leaf.subject.native.get("common_name")
                    issuer_cn = leaf.issuer.native.get("common_name")
                except Exception:  # noqa: BLE001 — identity label is best-effort, never load-bearing
                    pass
            ctx.shared["signer_identity"] = {"subject_cn": subject_cn, "issuer_cn": issuer_cn}
            measurements["signer_subject_cn"] = subject_cn
            measurements["signer_issuer_cn"] = issuer_cn
            pit_note = ""
            if any(s["point_in_time_validation"] for s in per_sig):
                signed_at = per_sig[0]["signer_reported_time"]
                pit_note = f"; certificate had since expired but was valid when signed ({signed_at})"
            return LayerSignal.valid(
                self.name,
                self.layer,
                self.mode,
                SUSPICION_VERIFIED,
                PROVENANCE_WEIGHT,
                "Legacy PDF signature (adbe.x509.rsa_sha1) verified: RSA-SHA1 signature intact, "
                f"chains to a pinned trust anchor, covers the whole file{pit_note}",
                measurements=measurements,
            )

        # Same carve-out as the CMS path (CLAUDE.md §3.1/§3.3): a cryptographically intact, unaltered
        # signature whose ONLY failure is an unpinned issuer is "source not confirmed", never tampering.
        content_intact_all = all(s["intact"] and s["valid"] and s["covers_whole_file"] for s in per_sig)
        if content_intact_all:
            untrusted_idx = [s["index"] for s in per_sig if not s["trusted"]]
            measurements["provenance"] = PROV_UNVERIFIED_ISSUER
            measurements["provenance_result"] = PROV_RESULT_NO_SOURCE
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "legacy PDF signature (adbe.x509.rsa_sha1) is cryptographically valid and the document "
                f"is unaltered, but the signer's certificate does not chain to a pinned trust anchor "
                f"(sig {untrusted_idx}) — issuer not confirmed. Routing to forensic verification.",
                **measurements,
            )

        reasons = []
        for s in per_sig:
            if s.get("error"):
                reasons.append(f"sig {s['index']}: {s['error']}")
            elif not s["intact"]:
                reasons.append(f"sig {s['index']}: RSA signature does not match the document bytes")
            elif not s["covers_whole_file"]:
                reasons.append(f"sig {s['index']}: does not cover the entire file")
        detail = "; ".join(reasons) or "signature present but did not verify"
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            SUSPICION_TAMPERED,
            PROVENANCE_WEIGHT,
            f"legacy PDF signature (adbe.x509.rsa_sha1) INVALID — tampering evidence ({detail})",
            measurements=measurements,
        )


class C2paProvenanceAnalyzer:
    """Validate a C2PA / Content-Credentials manifest on an image against a **pinned** trust list.

    Approach (BUILD-MANIFEST `BUILD_REAL_WORKS`): the c2pa SDK (over c2pa-rs) reads the manifest,
    verifies the COSE signature, the certificate chain, and the hard-binding hash against the file
    bytes. We pin a trust list (``verify.verify_trust`` + ``trust.trust_anchors``) so the documented
    self-signed-manifest exploit is rejected — an *unpinned* manifest validating its own self-signed
    cert is exactly the attack we must NOT pass.

    Decision: present + chain trusted -> *verified*; present + invalid/self-signed/untrusted ->
    *tampered*; absent (no manifest) -> ``NOT_EVALUATED`` (route to forensics — C2PA on bank
    statements is near-zero in the wild, a secondary image-path signal, never a gate); an asset we
    cannot even decode -> ``ERROR`` (fail-closed to REVIEW — "couldn't process" is not "tampered",
    §3.1). Absence is never an auto-pass; a parse failure is never a fabricated tamper verdict.
    """

    name = "c2pa_provenance"
    layer = 1
    mode = Mode.FILE
    order = 11

    # c2pa-rs ValidationState strings. "Trusted" = chain reached a pinned anchor; "Valid" = signature
    # validates but trust not asserted; "Invalid" = broken. We require Trusted to call it verified.
    _STATE_TRUSTED = "Trusted"
    _STATE_VALID = "Valid"
    _STATE_INVALID = "Invalid"

    _IMAGE_MAGIC = {
        b"\xff\xd8\xff": "image/jpeg",
        b"\x89PNG\r\n\x1a\n": "image/png",
        b"RIFF": "image/webp",
    }

    def __init__(self, anchor_dir: str | None = None) -> None:
        self._anchor_dir_override = anchor_dir

    def _sniff_mime(self, data: bytes) -> str | None:
        for magic, mime in self._IMAGE_MAGIC.items():
            if data[: len(magic)] == magic:
                # WebP needs "WEBP" at offset 8 to disambiguate from other RIFF containers.
                if mime == "image/webp" and data[8:12] != b"WEBP":
                    continue
                return mime
        return None

    def applicable(self, ctx: AnalysisContext) -> bool:
        if ctx.intake_mode != Mode.FILE or not ctx.file_bytes:
            return False
        return self._sniff_mime(ctx.file_bytes) is not None

    def _load_anchor_pems(self) -> list[str]:
        """Concatenate the pinned anchor PEMs as text for the c2pa trust list."""
        anchor_dir = _resolve_anchor_dir(self._anchor_dir_override)
        pems: list[str] = []
        if not anchor_dir.is_dir():
            return pems
        for path in sorted(anchor_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in (".pem", ".crt", ".cer"):
                try:
                    text = path.read_text(encoding="ascii", errors="strict")
                except (OSError, UnicodeDecodeError) as exc:
                    logger.warning("skipping non-PEM c2pa anchor %s: %s", path.name, exc)
                    continue
                if "BEGIN CERTIFICATE" in text:
                    pems.append(text)
        return pems

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if not ctx.file_bytes:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, "no file bytes to verify")
        mime = self._sniff_mime(ctx.file_bytes)
        if mime is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "not an image — C2PA path not applicable"
            )
        try:
            return self._analyze(ctx, mime)
        except Exception as exc:  # noqa: BLE001 — fail-closed boundary (§4)
            logger.exception("C2PA verification raised unexpectedly")
            return LayerSignal.error(self.name, self.layer, self.mode, f"C2PA verification failed: {exc!r}")

    def _analyze(self, ctx: AnalysisContext, mime: str) -> LayerSignal:
        import io

        from c2pa import C2paError, Context, Reader, Settings

        anchor_pems = self._load_anchor_pems()
        if not anchor_pems:
            # Fail-closed: an unpinned manifest is the documented self-signed exploit (§10).
            return LayerSignal.error(
                self.name,
                self.layer,
                self.mode,
                "no pinned C2PA trust anchors — refusing to validate an unpinned manifest",
            )

        # Pin the trust list and require cert-anchor verification (BUILD-MANIFEST cop-out guard).
        settings_obj = Settings.from_dict(
            {
                "verify": {"verify_trust": True, "verify_cert_anchors": True},
                "trust": {"trust_anchors": "\n".join(anchor_pems)},
            }
        )
        c2pa_ctx = Context(settings=settings_obj)

        try:
            with Reader(mime, io.BytesIO(ctx.file_bytes), context=c2pa_ctx) as reader:
                state = reader.get_validation_state()
        except C2paError as exc:
            kind = self._classify_c2pa_error(exc, C2paError)
            if kind == "absent":
                # No manifest at all -> route to Tier-2 forensics. Absence is never an auto-pass.
                return LayerSignal.not_evaluated(
                    self.name,
                    self.layer,
                    self.mode,
                    "no C2PA manifest present — routing to forensic fallback",
                    provenance=PROV_ABSENT,
                    method="C2PA",
                )
            if kind == "invalid":
                # A manifest IS present and its signature/chain/assertions failed -> tamper evidence.
                logger.info("C2PA manifest present but validation failed: %r", exc)
                return LayerSignal.valid(
                    self.name,
                    self.layer,
                    self.mode,
                    SUSPICION_TAMPERED,
                    PROVENANCE_WEIGHT,
                    f"C2PA manifest present but failed validation — tampering evidence ({exc!r})",
                    measurements={"provenance": PROV_TAMPERED, "method": "C2PA", "error": repr(exc)},
                )
            # kind == "unreadable": the asset itself could not be decoded/processed (corrupt or
            # unsupported). That is NOT a confident tamper claim (§3.1 honesty) — fail closed to
            # ERROR (-> human REVIEW), never an unearned "tampered" verdict and never a pass.
            logger.info("C2PA path could not process the asset: %r", exc)
            return LayerSignal.error(
                self.name,
                self.layer,
                self.mode,
                f"C2PA could not process the image (corrupt/unsupported asset): {exc!r}",
            )

        state_str = str(state) if state is not None else self._STATE_INVALID
        verified = self._STATE_TRUSTED in state_str  # require chain-to-pinned-anchor, not just "Valid"

        measurements: dict[str, Any] = {
            "provenance": PROV_VERIFIED if verified else PROV_TAMPERED,
            "method": "C2PA",
            "validation_state": state_str,
            "anchors_pinned": len(anchor_pems),
        }

        if verified:
            ctx.shared["provenance_verified"] = True
            return LayerSignal.valid(
                self.name,
                self.layer,
                self.mode,
                SUSPICION_VERIFIED,
                PROVENANCE_WEIGHT,
                "C2PA manifest verified: signature valid and chains to a pinned trust anchor",
                measurements=measurements,
            )

        # Present but not trusted (self-signed / untrusted chain / hard-binding mismatch).
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            SUSPICION_TAMPERED,
            PROVENANCE_WEIGHT,
            f"C2PA manifest present but not trusted (state={state_str}) — "
            "self-signed/unpinned manifest is the documented exploit; flagged",
            measurements=measurements,
        )

    @staticmethod
    def _classify_c2pa_error(exc: Exception, c2pa_error_cls: type) -> str:
        """Classify a c2pa SDK error as ``'absent' | 'invalid' | 'unreadable'``.

        Uses the SDK's **typed** error subclasses (``C2paError.ManifestNotFound`` etc.) rather than
        message-string sniffing, so the decision is robust across SDK versions and wording changes:

          * ``'absent'``     — no manifest / no JUMBF data  → route to Tier-2 forensics (NOT_EVALUATED).
          * ``'invalid'``    — a manifest IS present but its signature / chain / assertions failed
            validation  → a confident tamper claim.
          * ``'unreadable'`` — the asset could not be decoded/read (corrupt, unsupported, I/O) or any
            other/unexpected error  → fail-closed ERROR, never an unearned 'tampered'.

        We assert *invalid* (tampering) ONLY for kinds that mean "a manifest is present and its
        validation failed". Everything else — crucially, a file we could not even parse as an image —
        is *unreadable* and resolves to ERROR. Calling an unparseable upload "tampered" would be a
        §3.1 honesty violation (claiming a detection the analysis did not actually establish).
        """

        def _kinds(*names: str) -> tuple[type, ...]:
            return tuple(t for t in (getattr(c2pa_error_cls, n, None) for n in names) if isinstance(t, type))

        if isinstance(exc, _kinds("ManifestNotFound")):
            return "absent"
        if isinstance(exc, _kinds("Signature", "Verify", "Manifest", "Assertion", "AssertionNotFound")):
            return "invalid"
        return "unreadable"
