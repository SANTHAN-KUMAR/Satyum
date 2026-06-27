"""Tier-5 risk engine: aggregate signals into an explainable, fail-closed trust score.

Scoring rule (ADR-001 D-scoring / ADR-002):
  * Only ``VALID`` signals contribute. ``NOT_EVALUATED`` is excluded from BOTH the numerator and
    the denominator (never silently a pass). ``ERROR`` clamps the verdict to at most REVIEW.
  * trust_score = 100 * (1 - weighted_mean(suspicion over VALID signals)).
  * Provenance short-circuit: a cryptographically *verified* source answers integrity at the root
    (score is driven by the signature, CV forensics are excluded). A *tampered* signature (present
    but invalid) is active tampering evidence -> hard REJECT.
  * Substantive-evidence gate: on the forensic path, APPROVED requires that the document's CONTENT was
    actually assessed (a *substantive* signal evaluated — arithmetic consistency / active challenge),
    not merely that peripheral wrapper checks (PDF structure, perceptual-hash resubmission) found
    nothing. Clean wrapper + unread content == indeterminate -> REVIEW.
  * Fail-closed: any ERROR, or an indeterminate aggregate, degrades toward REVIEW/REJECT — never a
    silent APPROVE (CLAUDE.md §4, the cardinal banking rule).

This module is pure Python (no I/O, no heavy deps) and is unit-tested directly.
"""

from __future__ import annotations

from app.config import settings
from app.contracts import (
    LayerSignal,
    Mode,
    Provenance,
    SignalStatus,
    TrustScore,
    Verdict,
)


def _weighted_suspicion(signals: list[LayerSignal]) -> tuple[float, float]:
    """Return (weighted_mean_suspicion, total_weight) over VALID, positively-weighted signals."""
    num = 0.0
    den = 0.0
    for s in signals:
        if s.status != SignalStatus.VALID or s.weight <= 0.0 or s.suspicion is None:
            continue
        num += s.suspicion * s.weight
        den += s.weight
    if den == 0.0:
        return 0.0, 0.0
    return num / den, den


def derive_provenance(signals: list[LayerSignal]) -> Provenance:
    """Collapse the Tier-1 signature/provenance signals into a single Provenance verdict.

    A signature analyzer reports tampering via ``measurements["provenance"]`` = "verified" |
    "tampered" | "absent" and ``measurements["method"]``.
    """
    best = Provenance()
    for s in signals:
        if s.layer != 1 or "provenance" not in s.measurements:
            continue
        state = s.measurements.get("provenance")
        method = s.measurements.get("method", "unknown")
        if state == "tampered":
            # tampering beats everything — surface it
            return Provenance(verified=False, method=method, detail=s.reason, tampered=True)
        if state == "verified" and not best.verified:
            best = Provenance(verified=True, method=method, detail=s.reason, tampered=False)
    return best


def aggregate(
    session_id: str,
    intake_mode: Mode,
    signals: list[LayerSignal],
    *,
    doc_type: str | None = None,
    source_was_pullable: bool = False,
) -> TrustScore:
    provenance = derive_provenance(signals)
    has_error = any(s.status == SignalStatus.ERROR for s in signals)

    # --- Tier-1 short-circuits ------------------------------------------------------------
    if provenance.tampered:
        # signature present but invalid == active tampering -> hard REJECT, fail-closed
        return _finalise(
            session_id, intake_mode, doc_type, provenance, signals,
            score=5.0, verdict=Verdict.REJECTED, tier="source-verified",
            fail_closed=True,
        )

    if provenance.verified:
        # integrity proven cryptographically; CV forensics are NOT_EVALUATED ("provenance-trusted").
        # A red flag (PDF-only when a pull was possible) still applies a penalty but cannot, on its
        # own, reject a cryptographically genuine document.
        red_flag = _pdf_only_red_flag(signals)
        score = 99.0 - (15.0 if red_flag else 0.0)
        verdict = _verdict_from_score(score) if not has_error else Verdict.REVIEW
        return _finalise(
            session_id, intake_mode, doc_type, provenance, signals,
            score=score, verdict=verdict, tier="source-verified",
            fail_closed=has_error,
        )

    # --- Tier-2/3 forensic aggregation ----------------------------------------------------
    mean_susp, total_weight = _weighted_suspicion(signals)
    score = 100.0 * (1.0 - mean_susp)

    tier = "in-person-capture" if intake_mode == Mode.CAMERA else "forensic-fallback"

    if total_weight == 0.0:
        # nothing could be evaluated -> we cannot assert integrity -> fail-closed to REVIEW
        return _finalise(
            session_id, intake_mode, doc_type, provenance, signals,
            score=settings.review_at, verdict=Verdict.REVIEW, tier=tier,
            fail_closed=True,
        )

    verdict = _verdict_from_score(score)
    if has_error and verdict == Verdict.APPROVED:
        verdict = Verdict.REVIEW  # never auto-approve when something errored

    # Substantive-evidence gate (§4): APPROVED asserts the document is trustworthy — only honest when
    # its content was actually assessed. If the verdict would be APPROVED purely on clean peripheral
    # wrapper checks (structure/pHash) while no substantive content signal evaluated, the aggregate is
    # indeterminate -> downgrade to REVIEW (fail-closed), with the score pulled to the REVIEW band so
    # the gauge and verdict agree. (Provenance-verified documents already returned above.)
    if verdict == Verdict.APPROVED and not _substantive_signal_evaluated(signals):
        return _finalise(
            session_id, intake_mode, doc_type, provenance, signals,
            score=min(score, settings.review_at), verdict=Verdict.REVIEW, tier=tier,
            fail_closed=True,
        )

    return _finalise(
        session_id, intake_mode, doc_type, provenance, signals,
        score=score, verdict=verdict, tier=tier, fail_closed=has_error,
    )


def _substantive_signal_evaluated(signals: list[LayerSignal]) -> bool:
    """True iff a *substantive* content/integrity signal actually evaluated (status VALID).

    Clean peripheral wrapper checks (PDF structure, perceptual-hash resubmission) finding nothing is
    not positive evidence the financial content is genuine — only that the container looks unremarkable.
    APPROVED requires the content itself to have been assessed (ADR-002/003; §4 fail-closed). The set
    of substantive signal names is configured in ``settings.substantive_content_signals``.
    """
    return any(
        s.status == SignalStatus.VALID and s.name in settings.substantive_content_signals
        for s in signals
    )


def _pdf_only_red_flag(signals: list[LayerSignal]) -> bool:
    for s in signals:
        if s.measurements.get("red_flag") == "pdf_only_when_pullable":
            return True
    return False


def _verdict_from_score(score: float) -> Verdict:
    if score >= settings.approve_at:
        return Verdict.APPROVED
    if score >= settings.review_at:
        return Verdict.REVIEW
    return Verdict.REJECTED


def _finalise(
    session_id: str,
    intake_mode: Mode,
    doc_type: str | None,
    provenance: Provenance,
    signals: list[LayerSignal],
    *,
    score: float,
    verdict: Verdict,
    tier: str,
    fail_closed: bool,
) -> TrustScore:
    score = max(0.0, min(100.0, round(score, 2)))
    return TrustScore(
        session_id=session_id,
        intake_mode=intake_mode,
        doc_type=doc_type,
        provenance=provenance,
        trust_score=score,
        verdict=verdict,
        tier_reached=tier,
        signals=signals,
        fail_closed=fail_closed,
    )
