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
from typing import Any, Optional

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

logger = logging.getLogger(__name__)

# Provenance states surfaced in measurements['provenance'] (shared vocabulary with the UI/Provenance).
PROV_VERIFIED = "verified"  # intact + chains to a pinned anchor + covers the whole file
PROV_TAMPERED = "tampered"  # signature present but INVALID (forged chain / appended bytes / bad digest)
PROV_ABSENT = "absent"      # no signature at all -> route to Tier 2

# Suspicion is the binary cyber-fact: a verified chain is clean (0.0); an invalid one is active
# tampering evidence (1.0). There is no "somewhat signed" — a chain either reaches the anchor or not.
SUSPICION_VERIFIED = 0.0
SUSPICION_TAMPERED = 1.0

# Weight: Tier-1 provenance is the first-line control. When it speaks (verified/tampered) it is
# dispositive, so it carries full weight; ADR-002. DEFAULT — needs calibration against the corpus.
PROVENANCE_WEIGHT = 1.0

_PDF_MAGIC = b"%PDF-"


def _resolve_anchor_dir(override: Optional[str]) -> Path:
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

    def __init__(self, anchor_dir: Optional[str] = None) -> None:
        # Configurable so tests can pin a self-generated test CA as the trust root (§5 config-over-hardcode).
        self._anchor_dir_override = anchor_dir

    def applicable(self, ctx: AnalysisContext) -> bool:
        if ctx.intake_mode != Mode.FILE or not ctx.file_bytes:
            return False
        # Cheap structural gate: only run the PDF path on something that looks like a PDF.
        head = ctx.file_bytes[:1024]
        return _PDF_MAGIC in head[:8] or _PDF_MAGIC in head

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if not ctx.file_bytes:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no file bytes to verify"
            )
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

        anchor_dir = _resolve_anchor_dir(self._anchor_dir_override)
        trust_roots = _load_trust_roots(anchor_dir)
        if not trust_roots:
            # Fail-closed (§10): with no pinned anchors we cannot assert a chain — never auto-pass.
            return LayerSignal.error(
                self.name, self.layer, self.mode,
                f"no pinned trust anchors loaded from {anchor_dir} — cannot verify chain",
            )

        try:
            reader = PdfFileReader(io.BytesIO(ctx.file_bytes), strict=False)
            embedded = list(reader.embedded_signatures)
        except Exception as exc:  # noqa: BLE001 — malformed PDF is ordinary bad input, fail-closed
            logger.warning("could not parse PDF for signature extraction: %r", exc)
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"unparsable PDF: {exc!r}"
            )

        if not embedded:
            # Absent -> NOT_EVALUATED: route to Tier 2 forensics. Absence is never an auto-pass.
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no embedded PAdES/CMS signature — routing to forensic fallback",
                provenance=PROV_ABSENT, method="PAdES",
            )

        vc = ValidationContext(trust_roots=trust_roots, allow_fetching=False)

        # Evaluate every signature; the document is only verified if ALL present signatures verify
        # and at least one covers the whole file. Any failing/under-covering signature is tampering.
        per_sig: list[dict[str, Any]] = []
        all_verified = True
        whole_file_covered = False

        for idx, emb in enumerate(embedded):
            try:
                status = validate_pdf_signature(emb, signer_validation_context=vc)
                intact = bool(status.intact)
                valid = bool(status.valid)
                trusted = bool(status.trusted)
                coverage = status.coverage
            except PathValidationError as exc:
                # Chain explicitly failed to reach a pinned anchor (attacker / self-signed cert).
                logger.info("signature %d chain validation failed: %s", idx, exc)
                intact = valid = trusted = False
                coverage = SignatureCoverageLevel.UNCLEAR
            except Exception as exc:  # noqa: BLE001 — a per-signature failure must not pass-through
                logger.warning("signature %d validation raised: %r", idx, exc)
                intact = valid = trusted = False
                coverage = SignatureCoverageLevel.UNCLEAR

            covers_whole = coverage == SignatureCoverageLevel.ENTIRE_FILE
            sig_verified = intact and valid and trusted and covers_whole
            all_verified = all_verified and sig_verified
            whole_file_covered = whole_file_covered or covers_whole

            per_sig.append({
                "index": idx,
                "intact": intact,        # digest matches the covered bytes
                "valid": valid,          # CMS/PKCS#7 math validates
                "trusted": trusted,      # chain reaches a pinned anchor
                "covers_whole_file": covers_whole,  # no appended bytes after /ByteRange
                "coverage": coverage.name if coverage is not None else "NONE",
            })

        verified = all_verified and whole_file_covered
        measurements: dict[str, Any] = {
            "provenance": PROV_VERIFIED if verified else PROV_TAMPERED,
            "method": "PAdES",
            "signature_count": len(embedded),
            "anchors_pinned": len(trust_roots),
            "signatures": per_sig,
        }

        if verified:
            # Source-of-truth answered at the PKI root: publish for downstream analyzers / red-flag.
            ctx.shared["provenance_verified"] = True
            return LayerSignal.valid(
                self.name, self.layer, self.mode,
                SUSPICION_VERIFIED, PROVENANCE_WEIGHT,
                "PAdES signature verified: intact, chains to a pinned trust anchor, covers the whole file",
                measurements=measurements,
            )

        # Present but invalid: forged chain, appended bytes, or broken digest -> active tamper evidence.
        reasons = []
        for s in per_sig:
            if not s["trusted"]:
                reasons.append(f"sig {s['index']}: chain does not reach a pinned anchor")
            elif not s["intact"] or not s["valid"]:
                reasons.append(f"sig {s['index']}: cryptographic digest/signature invalid")
            elif not s["covers_whole_file"]:
                reasons.append(
                    f"sig {s['index']}: bytes appended after /ByteRange (coverage={s['coverage']})"
                )
        detail = "; ".join(reasons) or "signature present but did not verify"
        return LayerSignal.valid(
            self.name, self.layer, self.mode,
            SUSPICION_TAMPERED, PROVENANCE_WEIGHT,
            f"PAdES signature INVALID — tampering evidence ({detail})",
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

    def __init__(self, anchor_dir: Optional[str] = None) -> None:
        self._anchor_dir_override = anchor_dir

    def _sniff_mime(self, data: bytes) -> Optional[str]:
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
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no file bytes to verify"
            )
        mime = self._sniff_mime(ctx.file_bytes)
        if mime is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "not an image — C2PA path not applicable"
            )
        try:
            return self._analyze(ctx, mime)
        except Exception as exc:  # noqa: BLE001 — fail-closed boundary (§4)
            logger.exception("C2PA verification raised unexpectedly")
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"C2PA verification failed: {exc!r}"
            )

    def _analyze(self, ctx: AnalysisContext, mime: str) -> LayerSignal:
        import io

        from c2pa import C2paError, Context, Reader, Settings

        anchor_pems = self._load_anchor_pems()
        if not anchor_pems:
            # Fail-closed: an unpinned manifest is the documented self-signed exploit (§10).
            return LayerSignal.error(
                self.name, self.layer, self.mode,
                "no pinned C2PA trust anchors — refusing to validate an unpinned manifest",
            )

        # Pin the trust list and require cert-anchor verification (BUILD-MANIFEST cop-out guard).
        settings_obj = Settings.from_dict({
            "verify": {"verify_trust": True, "verify_cert_anchors": True},
            "trust": {"trust_anchors": "\n".join(anchor_pems)},
        })
        c2pa_ctx = Context(settings=settings_obj)

        try:
            with Reader(mime, io.BytesIO(ctx.file_bytes), context=c2pa_ctx) as reader:
                state = reader.get_validation_state()
        except C2paError as exc:
            kind = self._classify_c2pa_error(exc, C2paError)
            if kind == "absent":
                # No manifest at all -> route to Tier-2 forensics. Absence is never an auto-pass.
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    "no C2PA manifest present — routing to forensic fallback",
                    provenance=PROV_ABSENT, method="C2PA",
                )
            if kind == "invalid":
                # A manifest IS present and its signature/chain/assertions failed -> tamper evidence.
                logger.info("C2PA manifest present but validation failed: %r", exc)
                return LayerSignal.valid(
                    self.name, self.layer, self.mode,
                    SUSPICION_TAMPERED, PROVENANCE_WEIGHT,
                    f"C2PA manifest present but failed validation — tampering evidence ({exc!r})",
                    measurements={"provenance": PROV_TAMPERED, "method": "C2PA", "error": repr(exc)},
                )
            # kind == "unreadable": the asset itself could not be decoded/processed (corrupt or
            # unsupported). That is NOT a confident tamper claim (§3.1 honesty) — fail closed to
            # ERROR (-> human REVIEW), never an unearned "tampered" verdict and never a pass.
            logger.info("C2PA path could not process the asset: %r", exc)
            return LayerSignal.error(
                self.name, self.layer, self.mode,
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
                self.name, self.layer, self.mode,
                SUSPICION_VERIFIED, PROVENANCE_WEIGHT,
                "C2PA manifest verified: signature valid and chains to a pinned trust anchor",
                measurements=measurements,
            )

        # Present but not trusted (self-signed / untrusted chain / hard-binding mismatch).
        return LayerSignal.valid(
            self.name, self.layer, self.mode,
            SUSPICION_TAMPERED, PROVENANCE_WEIGHT,
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
            return tuple(
                t for t in (getattr(c2pa_error_cls, n, None) for n in names) if isinstance(t, type)
            )

        if isinstance(exc, _kinds("ManifestNotFound")):
            return "absent"
        if isinstance(exc, _kinds("Signature", "Verify", "Manifest", "Assertion", "AssertionNotFound")):
            return "invalid"
        return "unreadable"
