"""Bundle verification — run the per-document waterfall over an application bundle, then cross-check.

This sits ABOVE the single-document orchestrator (``app/orchestrator.run_verification``). A bank loan
application is a *bundle* (bank statement + ID + deed). Each document is verified individually first;
then the bundle-level **cross-document consistency graph** (ADR-003 #3) asks whether the identities
agree across them. The bundle is fail-closed: never more trusting than its worst document, and a
cross-document identity mismatch drives the bundle verdict down hard.
"""

from __future__ import annotations

from app.config import settings
from app.contracts import (
    AnalysisContext,
    BundleDocument,
    BundleTrustScore,
    LayerSignal,
    Mode,
    Provenance,
    SignalStatus,
    TrustScore,
    Verdict,
)
from app.orchestrator import run_verification
from app.registry import AnalyzerRegistry
from forensics.cross_document import cross_document_signal
from forensics.entities import ExtractedEntities
from risk.audit import AuditLedger

_VERDICT_RANK = {Verdict.APPROVED: 0, Verdict.REVIEW: 1, Verdict.REJECTED: 2}


def _verdict_from_score(score: float) -> Verdict:
    if score >= settings.approve_at:
        return Verdict.APPROVED
    if score >= settings.review_at:
        return Verdict.REVIEW
    return Verdict.REJECTED


def _more_severe(a: Verdict, b: Verdict) -> Verdict:
    return a if _VERDICT_RANK[a] >= _VERDICT_RANK[b] else b


def verify_bundle(
    labelled_contexts: list[tuple[str, AnalysisContext]],
    registry: AnalyzerRegistry,
    ledger: AuditLedger,
    timestamp_iso: str,
    *,
    bundle_session_id: str,
) -> BundleTrustScore:
    """Verify each document, extract its entities, then run the cross-document consistency graph."""
    documents: list[BundleDocument] = []
    entities_by_doc: dict[str, ExtractedEntities] = {}

    for label, ctx in labelled_contexts:
        try:
            trust = run_verification(ctx, registry, ledger, timestamp_iso)
        except Exception as exc:  # noqa: BLE001 — one bad document must never crash the bundle (§4)
            trust = _failed_document_trust(ctx.session_id, exc)
        documents.append(BundleDocument(label=label, trust=trust))
        # EntityExtractionAnalyzer publishes this during the per-doc waterfall (FILE mode).
        ent = ctx.shared.get("entities")
        entities_by_doc[label] = ent if isinstance(ent, ExtractedEntities) else ExtractedEntities()

    try:
        cross = cross_document_signal(entities_by_doc)
    except Exception as exc:  # noqa: BLE001 — a cross-check failure is fail-closed, never a crash (§4)
        cross = LayerSignal.error(
            "cross_document_consistency", 2, Mode.FILE, f"cross-document check failed: {exc!r}"
        )
    bundle = _aggregate_bundle(bundle_session_id, documents, cross)

    ledger.record(
        timestamp_iso,
        {
            "session_id": bundle.session_id,
            "kind": "bundle",
            "document_count": bundle.document_count,
            "bundle_verdict": bundle.bundle_verdict.value,
            "bundle_score": bundle.bundle_score,
            "fail_closed": bundle.fail_closed,
            "cross_document": {
                "status": cross.status.value,
                "suspicion": cross.suspicion,
                "disagreeing_fields": cross.measurements.get("disagreeing_fields", []),
            },
            "documents": [
                {"label": d.label, "verdict": d.trust.verdict.value,
                 "score": d.trust.trust_score} for d in documents
            ],
        },
    )
    return bundle


def _failed_document_trust(session_id: str, exc: Exception) -> TrustScore:
    """A fail-closed REJECTED stand-in for a document whose verification crashed (§4)."""
    return TrustScore(
        session_id=session_id,
        intake_mode=Mode.FILE,
        doc_type=None,
        provenance=Provenance(detail=f"document verification failed: {exc!r}"),
        trust_score=0.0,
        verdict=Verdict.REJECTED,
        tier_reached="forensic-fallback",
        signals=[LayerSignal.error("bundle_document", 1, Mode.FILE,
                                   f"document verification raised: {exc!r}")],
        evidence_pack={},
        fail_closed=True,
    )


def _aggregate_bundle(
    session_id: str, documents: list[BundleDocument], cross: LayerSignal
) -> BundleTrustScore:
    """Fail-closed bundle aggregation: worst document AND the cross-document signal both bind.

    The cross-document signal floors the verdict INDEPENDENTLY of the score (M1 defense-in-depth):
    a true hard-identifier mismatch -> REJECTED; an OCR near-match or name-only disagreement -> at
    least REVIEW. So the fail-closed flag and the verdict can never diverge from a severity constant.
    """
    meas = cross.measurements or {}
    hard_mismatch = bool(meas.get("hard_mismatch_fields"))
    disagreeing = meas.get("disagreeing_fields", [])
    cross_valid = cross.status == SignalStatus.VALID
    cross_mismatch = cross_valid and bool(disagreeing)

    doc_scores = [d.trust.trust_score for d in documents]
    min_doc_score = min(doc_scores) if doc_scores else 0.0
    cross_score = 100.0 * (1.0 - cross.suspicion) if (cross_valid and cross.suspicion is not None) else 100.0

    bundle_score = max(0.0, min(min_doc_score, cross_score))
    verdict = _verdict_from_score(bundle_score)

    # Never more trusting than the worst individual document.
    for d in documents:
        verdict = _more_severe(verdict, d.trust.verdict)
    # Cross-document floor (independent of the score path).
    if hard_mismatch:
        verdict = _more_severe(verdict, Verdict.REJECTED)
    elif cross_mismatch:
        verdict = _more_severe(verdict, Verdict.REVIEW)

    fail_closed = (
        cross_mismatch
        or cross.status == SignalStatus.ERROR
        or any(d.trust.fail_closed for d in documents)
    )

    reasons: list[str] = []
    if hard_mismatch:
        reasons.append(f"Cross-document identity mismatch: {cross.reason}")
    elif cross_mismatch:
        reasons.append(f"Cross-document soft discrepancy (manual review): {cross.reason}")
    elif cross_valid:
        reasons.append(f"Cross-document identity corroborated: {cross.reason}")
    else:
        reasons.append(f"Cross-document check not evaluated: {cross.reason}")
    for d in documents:
        if d.trust.verdict == Verdict.REJECTED:
            reasons.append(f"{d.label}: REJECTED ({d.trust.provenance.detail or 'see signals'}).")

    return BundleTrustScore(
        session_id=session_id,
        document_count=len(documents),
        documents=documents,
        cross_document=cross,
        bundle_score=round(bundle_score, 2),
        bundle_verdict=verdict,
        fail_closed=fail_closed,
        reasons=reasons,
    )
