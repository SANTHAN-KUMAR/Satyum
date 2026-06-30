"""DigiLocker provider — Path B (offline signature verify, no-partner hero) + Path A (gated).

PROPOSAL-001 §2.7 / §4.3 and BUILD-MANIFEST distinguish two very different DigiLocker integrations:

  * **Path B — offline signature verification (no partner).** A DigiLocker *Issued Document* is a PDF
    PAdES-signed under the CCA-India PKI by NeGD. You do **not** need the pull API to trust it: verify
    the embedded signature offline against the pinned CCA root. This is exactly what
    ``verification/signature.PadesSignatureAnalyzer`` already does — so this provider **delegates the
    verdict to that one real verifier** (single source of truth) and normalises it into a
    :class:`SourceResult`, adding the issuer identity for the "issued by X · CCA-signed" trust badge.
    It is verifiable *today*, on a real signed PDF.

  * **Path A — Issued-Documents pull API (partner-gated).** Server-side OAuth into the citizen's
    DigiLocker to pull issued docs requires NeGD / Meri Pehchan *requester* onboarding and an entity
    agreement. We never fake a "live DigiLocker pull": when a live pull is requested (no document
    bytes supplied) we return an honest, precisely-labelled gate.

Integrity (CLAUDE.md §3.1): VERIFIED is earned only by a real signature that chains to a pinned
anchor — never fabricated. A present-but-invalid signature is INVALID (tamper evidence); an unsigned
PDF is ABSENT (route to the manual/forensic fallback, never an auto-pass).
"""

from __future__ import annotations

import logging

from app.contracts import AnalysisContext, Mode, SignalStatus
from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    ProvenanceMode,
    SignatureStatus,
    SourceResult,
)
from verification.signature import (
    PROV_TAMPERED,
    PROV_UNVERIFIED_ISSUER,
    PROV_VERIFIED,
    PadesSignatureAnalyzer,
)

logger = logging.getLogger(__name__)

# Document classes for which a DigiLocker-issued / CCA-signed PDF is a meaningful source.
_DIGILOCKER_CLASSES = frozenset({
    DocClass.FINANCIAL_STATEMENT,
    DocClass.IDENTITY,
    DocClass.LAND_RECORD,
    DocClass.LEGAL_DEED,
})

# The precise gate for the live Issued-Documents pull (Path A). Never simulated as live.
_PATH_A_GATE = (
    "DigiLocker Issued-Documents pull (Path A) requires NeGD / Meri Pehchan requester onboarding and "
    "an entity agreement — gated. Path B (offline signature verification of the issued PDF) is fully "
    "real and used here; supply the signed document to verify it at source."
)


class DigiLockerProvider:
    """DigiLocker source-pull adapter. ``fetch`` with bytes → Path B verify; without → Path A gate."""

    name = "digilocker"

    def __init__(self, anchor_dir: str | None = None) -> None:
        # Configurable trust store so tests pin a throwaway test CA and prod pins the CCA-India root
        # (§5 config-over-hardcode) — threaded straight into the real PAdES analyzer.
        self._anchor_dir = anchor_dir

    def applicable(self, doc_request: DocRequest) -> bool:
        return doc_request.doc_class in _DIGILOCKER_CLASSES

    def fetch(
        self,
        consent: ConsentArtifact,
        doc_request: DocRequest,
        payload: bytes | None = None,
    ) -> SourceResult:
        if payload is None:
            # A live Issued-Documents pull was requested but is partner-gated — be honest, never fake.
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.SOURCE_PULL,
                gate=_PATH_A_GATE,
                detail="live DigiLocker pull is partner-gated; supply the signed PDF for Path B verification",
            )
        return self._verify_path_b(doc_request, payload)

    def _verify_path_b(self, doc_request: DocRequest, payload: bytes) -> SourceResult:
        """Offline PAdES verification of an issuer-signed PDF, via the real Tier-1 analyzer."""
        ctx = AnalysisContext(
            session_id="source-pull",
            intake_mode=Mode.FILE,
            doc_type=doc_request.doc_class.value,
            file_bytes=payload,
            file_name="digilocker_issued.pdf",
            file_mime="application/pdf",
        )
        analyzer = PadesSignatureAnalyzer(anchor_dir=self._anchor_dir)
        if not analyzer.applicable(ctx):
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.ABSENT,
                provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
                detail="supplied payload is not a PDF — no DigiLocker-issued signature to verify",
            )

        signal = analyzer.analyze(ctx)
        provenance = signal.measurements.get("provenance")
        issuer = self._issuer_from_context(ctx)

        if signal.status == SignalStatus.VALID and provenance == PROV_VERIFIED:
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.VERIFIED,
                provenance_mode=ProvenanceMode.SOURCE_PULL,
                issuer=issuer,
                detail=(
                    "verified at source — CCA-chained PAdES signature valid"
                    + (f", issued by {issuer}" if issuer else "")
                ),
                measurements=signal.measurements,
                signed_bytes=payload,  # hand the verified bytes onward to the full verification core
            )

        if signal.status == SignalStatus.VALID and provenance == PROV_TAMPERED:
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.INVALID,
                provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
                issuer=issuer,
                detail=f"signature present but INVALID — tampering evidence ({signal.reason})",
                measurements=signal.measurements,
            )

        if signal.status == SignalStatus.NOT_EVALUATED and provenance == PROV_UNVERIFIED_ISSUER:
            # Signature present and cryptographically valid, but its chain does not reach a pinned
            # anchor — the issuer cannot be confirmed. This is NOT "absent" (there IS a signature) and
            # NOT "tampered" (the bytes are intact): it is NOT_VERIFIED — we could not confirm the
            # source. Honest, never a fabricated tamper verdict (§3.1). Pin the issuer root to verify it.
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
                issuer=issuer,
                detail=f"signature valid but issuer not confirmed (chain not pinned) — {signal.reason}",
                measurements=signal.measurements,
            )

        if signal.status == SignalStatus.NOT_EVALUATED:
            # No embedded signature — this isn't a DigiLocker-issued artifact; route to the fallback.
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.ABSENT,
                provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
                detail="no embedded signature — not a DigiLocker-issued document; route to forensic fallback",
                measurements=signal.measurements,
            )

        # ERROR (no pinned anchors, unparsable PDF, …) → fail-closed, never a fabricated pass (§4).
        return SourceResult(
            provider=self.name,
            doc_class=doc_request.doc_class,
            signature_status=SignatureStatus.NOT_VERIFIED,
            provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
            detail=f"could not verify signature (fail-closed): {signal.reason}",
            measurements=signal.measurements,
        )

    @staticmethod
    def _issuer_from_context(ctx: AnalysisContext) -> str | None:
        """Best-effort issuer name from the verified signer cert (published by the analyzer).

        Never affects the verdict — purely the human-readable "issued by X" badge. Absent → ``None``.
        """
        identity = ctx.shared.get("signer_identity")
        if isinstance(identity, dict):
            return identity.get("subject_cn") or identity.get("issuer_cn")
        return None
