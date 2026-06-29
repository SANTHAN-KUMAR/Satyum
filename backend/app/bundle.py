"""Bundle verification — run the per-document waterfall over an application bundle, then cross-check.

This sits ABOVE the single-document orchestrator (``app/orchestrator.run_verification``). A bank loan
application is a *bundle* (bank statement + ID + deed). Each document is verified individually first;
then the bundle-level **cross-document consistency graph** (ADR-003 #3) asks whether the identities
agree across them. The bundle is fail-closed: never more trusting than its worst document, and a
cross-document identity mismatch drives the bundle verdict down hard.
"""

from __future__ import annotations

from app.claims import ClaimGraph
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
from app.orchestrator import audit_trust, collect_signals
from app.registry import AnalyzerRegistry
from forensics.cross_document import cross_document_signal
from forensics.entities import ExtractedEntities
from risk.audit import AuditLedger
from risk.engine import aggregate
from risk.evidence import build_evidence_pack
from rules.corroboration import cross_source_signal

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
    """Run each document's waterfall, compute the bundle-level corroboration, then aggregate.

    Two passes (ADR-004 §6): pass 1 collects every document's signals AND publishes its entities +
    claim graph; the bundle-level cross-checks (identity over entities, income/employer over claim
    graphs) need ALL documents at once, so they run between the passes; pass 2 aggregates each document
    *with the income corroboration injected*, so a clean financial document that the bundle corroborates
    can reach APPROVE — which a per-document-first aggregation (every lone doc REVIEW) could never give.
    """
    collected: list[tuple[str, AnalysisContext, list[LayerSignal] | None, Exception | None]] = []
    entities_by_doc: dict[str, ExtractedEntities] = {}
    graphs_by_doc: dict[str, ClaimGraph] = {}

    # --- Pass 1: run analyzers per document (isolated — one crash never fails the bundle, §4) ------
    for label, ctx in labelled_contexts:
        try:
            signals: list[LayerSignal] | None = collect_signals(ctx, registry)
            crash: Exception | None = None
        except Exception as exc:  # noqa: BLE001 — one bad document must never crash the bundle (§4)
            signals, crash = None, exc
        collected.append((label, ctx, signals, crash))
        ent = ctx.shared.get("entities")
        entities_by_doc[label] = ent if isinstance(ent, ExtractedEntities) else ExtractedEntities()
        graph = ctx.shared.get("claim_graph")
        if isinstance(graph, ClaimGraph):
            graphs_by_doc[label] = graph

    # --- Bundle-level cross-checks (fail-closed: a cross-check error is never a crash) -------------
    identity_cross = _safe_signal(
        "cross_document_consistency", lambda: cross_document_signal(entities_by_doc)
    )
    income_cross = _safe_signal(
        "cross_source_corroboration", lambda: cross_source_signal(graphs_by_doc)
    )

    # --- Pass 2: aggregate each document, injecting the income corroboration so it can lift/lower ---
    inject = [income_cross] if income_cross.status == SignalStatus.VALID else []
    documents: list[BundleDocument] = []
    for label, ctx, signals, crash in collected:
        if signals is None:
            trust = _failed_document_trust(ctx.session_id, crash or RuntimeError("verification failed"))
        else:
            trust = aggregate(
                ctx.session_id, ctx.intake_mode, signals + inject,
                doc_type=ctx.doc_type, source_was_pullable=ctx.source_was_pullable,
            )
            trust.evidence_pack = build_evidence_pack(trust)
            audit_trust(ledger, timestamp_iso, trust)
        documents.append(BundleDocument(label=label, trust=trust))

    bundle = _aggregate_bundle(bundle_session_id, documents, identity_cross, income_cross)

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
                "status": identity_cross.status.value,
                "suspicion": identity_cross.suspicion,
                "disagreeing_fields": identity_cross.measurements.get("disagreeing_fields", []),
            },
            "cross_source": {
                "status": income_cross.status.value,
                "suspicion": income_cross.suspicion,
                "disagreeing_checks": income_cross.measurements.get("disagreeing_checks", []),
            },
            "documents": [
                {"label": d.label, "verdict": d.trust.verdict.value,
                 "score": d.trust.trust_score} for d in documents
            ],
        },
    )
    return bundle


def _safe_signal(name: str, build: object) -> LayerSignal:
    """Run a bundle-level cross-check, degrading a failure to a fail-closed ERROR signal (§4)."""
    try:
        return build()  # type: ignore[operator]
    except Exception as exc:  # noqa: BLE001 — a cross-check failure is fail-closed, never a crash
        return LayerSignal.error(name, 2, Mode.FILE, f"{name} check failed: {exc!r}")


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
    session_id: str,
    documents: list[BundleDocument],
    identity_cross: LayerSignal,
    income_cross: LayerSignal,
) -> BundleTrustScore:
    """Fail-closed bundle aggregation: the worst document AND both bundle cross-checks bind.

    Each cross-check floors the verdict INDEPENDENTLY of the score (defence-in-depth):
      * identity (cross_document_consistency): a true hard-identifier mismatch -> REJECTED; an OCR
        near-match or name-only disagreement -> at least REVIEW;
      * income (cross_source_corroboration): a figure-level disagreement across sources -> at least
        REVIEW (a soft, human-reconciled signal — never an auto-reject on its own).
    So the fail-closed flag and the verdict can never diverge from a severity constant.
    """
    imeas = identity_cross.measurements or {}
    hard_mismatch = bool(imeas.get("hard_mismatch_fields"))
    identity_valid = identity_cross.status == SignalStatus.VALID
    identity_mismatch = identity_valid and bool(imeas.get("disagreeing_fields"))

    income_valid = income_cross.status == SignalStatus.VALID
    income_mismatch = income_valid and bool(income_cross.measurements.get("disagreeing_checks"))

    doc_scores = [d.trust.trust_score for d in documents]
    min_doc_score = min(doc_scores) if doc_scores else 0.0
    # The bundle score is never more than its worst document or its weakest cross-check.
    cross_score = min(
        _signal_score(identity_cross),
        _signal_score(income_cross),
    )
    bundle_score = max(0.0, min(min_doc_score, cross_score))
    verdict = _verdict_from_score(bundle_score)

    # Never more trusting than the worst individual document.
    for d in documents:
        verdict = _more_severe(verdict, d.trust.verdict)
    # Cross-check floors (independent of the score path).
    if hard_mismatch:
        verdict = _more_severe(verdict, Verdict.REJECTED)
    elif identity_mismatch or income_mismatch:
        verdict = _more_severe(verdict, Verdict.REVIEW)

    fail_closed = (
        identity_mismatch
        or income_mismatch
        or identity_cross.status == SignalStatus.ERROR
        or income_cross.status == SignalStatus.ERROR
        or any(d.trust.fail_closed for d in documents)
    )

    reasons: list[str] = []
    if hard_mismatch:
        reasons.append(f"Cross-document identity mismatch: {identity_cross.reason}")
    elif identity_mismatch:
        reasons.append(f"Cross-document soft discrepancy (manual review): {identity_cross.reason}")
    elif identity_valid:
        reasons.append(f"Cross-document identity corroborated: {identity_cross.reason}")
    else:
        reasons.append(f"Cross-document identity check not evaluated: {identity_cross.reason}")
    if income_mismatch:
        reasons.append(f"Cross-source income discrepancy (manual review): {income_cross.reason}")
    elif income_valid:
        reasons.append(f"Cross-source income corroborated: {income_cross.reason}")
    for d in documents:
        if d.trust.verdict == Verdict.REJECTED:
            reasons.append(f"{d.label}: REJECTED ({d.trust.provenance.detail or 'see signals'}).")

    return BundleTrustScore(
        session_id=session_id,
        document_count=len(documents),
        documents=documents,
        cross_document=identity_cross,
        corroboration=[identity_cross, income_cross],
        bundle_score=round(bundle_score, 2),
        bundle_verdict=verdict,
        fail_closed=fail_closed,
        reasons=reasons,
    )


def _signal_score(cross: LayerSignal) -> float:
    """The 0..100 score contribution of a bundle cross-check: 100 unless it VALID-fires a suspicion."""
    if cross.status == SignalStatus.VALID and cross.suspicion is not None:
        return 100.0 * (1.0 - cross.suspicion)
    return 100.0
