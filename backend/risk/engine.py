"""Tier-5 risk engine: aggregate signals into an explainable, fail-closed trust score.

Scoring rule (ADR-001 D-scoring / ADR-002):
  * Only ``VALID`` signals contribute. ``NOT_EVALUATED`` is excluded from BOTH the numerator and
    the denominator (never silently a pass). ``ERROR`` clamps the verdict to at most REVIEW.
  * trust_score = 100 * (1 - weighted_mean(suspicion over VALID signals)).
  * Provenance floor (ADR-004 §Layer-1): a cryptographically *verified* source sets a high trust FLOOR
    but is byte-authenticity, not claim-truthfulness — the claims still flow, so a corroboration mismatch
    can pull a verified document down. A *tampered* signature (present but invalid) -> hard REJECT.
  * Corroboration gate (ADR-004 §7 #2): on the forensic (un-provenanced) FILE path, APPROVED requires the
    CONTENT to have been assessed (a substantive signal) AND cross-source corroboration — clean rules
    alone are necessary but not sufficient (a recomputed reprint passes them). Lone unsigned doc -> REVIEW.
  * Fail-closed: any ERROR, or an indeterminate aggregate, degrades toward REVIEW/REJECT — never a
    silent APPROVE (CLAUDE.md §4, the cardinal banking rule).

Golden-rule guards (ADR-004 §7) are enforced as explicit, property-tested invariants:
  * hard-reject triggers (tampered provenance / hard identity mismatch / known fraud-ring reuse, via
    ``measurements["hard_reject"]``) → REJECT, fail-closed, undiluted by clean signals;
  * a REVIEW-only signal (anomaly intelligence) can never, on its own, drive a REJECT;
  * (existing) ERROR never auto-approves; a clean wrapper without substantive content assessment → REVIEW.

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

    # --- Golden-rule guard: hard-reject triggers (ADR-004 §7) -----------------------------
    # Tampered provenance, a hard cross-document identity mismatch, or a known fraud-ring reuse are
    # dispositive: REJECT, fail-closed, regardless of any other clean signal. Tampered provenance is
    # surfaced with the source tier; any other analyzer raises it via measurements["hard_reject"]=True.
    if provenance.tampered:
        # signature present but invalid == active tampering -> hard REJECT, fail-closed
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=5.0,
            verdict=Verdict.REJECTED,
            tier="source-verified",
            fail_closed=True,
        )
    hard_reject = _hard_reject_trigger(signals)
    if hard_reject is not None:
        tier = "in-person-capture" if intake_mode == Mode.CAMERA else "forensic-fallback"
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=5.0,
            verdict=Verdict.REJECTED,
            tier=tier,
            fail_closed=True,
        )

    if provenance.verified:
        # Verified = byte-authenticity, NOT claim-truthfulness (ADR-004 §Layer-1): the signature sets a
        # high trust FLOOR, but the claims still flow — a corroboration mismatch or a rule contradiction
        # can pull a cryptographically genuine document down (a signed statement can still carry income
        # that contradicts the ITR). The PDF-only red flag (a fresher pull was avoided) lowers the floor.
        floor = 99.0 - (15.0 if _pdf_only_red_flag(signals) else 0.0)
        contra_mean, contra_weight = _weighted_suspicion(_contradiction_signals(signals))
        forensic = round(100.0 * (1.0 - contra_mean), 2) if contra_weight > 0.0 else floor
        score = min(floor, forensic)
        verdict = _verdict_from_score(score) if not has_error else Verdict.REVIEW
        # A REVIEW-only signal must not, on its own, reject a verified document (golden rule #3).
        if verdict == Verdict.REJECTED and _reject_caused_only_by_review_only(signals):
            verdict, score = Verdict.REVIEW, max(score, settings.review_at)
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=score,
            verdict=verdict,
            tier="source-verified",
            fail_closed=has_error,
        )

    # --- Tier-2/3 forensic aggregation ----------------------------------------------------
    mean_susp, total_weight = _weighted_suspicion(signals)
    # Round ONCE here so the verdict band and the displayed gauge are derived from the same value.
    # (Deriving the verdict from an unrounded score while the gauge shows a rounded one let a float
    # artefact like 59.999999999999986 read as REJECTED while the gauge showed 60.0 / REVIEW.)
    score = round(100.0 * (1.0 - mean_susp), 2)

    tier = "in-person-capture" if intake_mode == Mode.CAMERA else "forensic-fallback"

    if total_weight == 0.0:
        # nothing could be evaluated -> we cannot assert integrity -> fail-closed to REVIEW
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=settings.review_at,
            verdict=Verdict.REVIEW,
            tier=tier,
            fail_closed=True,
        )

    verdict = _verdict_from_score(score)
    if has_error and verdict == Verdict.APPROVED:
        # Never auto-approve when something errored. Also cap the displayed score to the top of
        # the REVIEW band so the gauge and verdict band are consistent (100/100 + REVIEW is
        # confusing; 84/100 + REVIEW clearly communicates "close but blocked by an error").
        verdict = Verdict.REVIEW
        score = min(score, settings.approve_at - 1)

    # Golden-rule guard (ADR-004 §7): a REVIEW-only signal (anomaly intelligence, Layer 5) can never,
    # on its own, drive a REJECT. If removing the review-only signals would lift the verdict out of the
    # reject band, the reject was caused by them -> downgrade to REVIEW (the gauge is pulled up to agree).
    if verdict == Verdict.REJECTED and _reject_caused_only_by_review_only(signals):
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=max(score, settings.review_at),
            verdict=Verdict.REVIEW,
            tier=tier,
            fail_closed=True,
        )

    # Substantive-evidence gate (§4): APPROVED asserts the document is trustworthy — only honest when
    # its content was actually assessed. If the verdict would be APPROVED purely on clean peripheral
    # wrapper checks (structure/pHash) while no substantive content signal evaluated, the aggregate is
    # indeterminate -> downgrade to REVIEW (fail-closed), with the score pulled to the REVIEW band so
    # the gauge and verdict agree. (Provenance-verified documents already returned above.)
    if verdict == Verdict.APPROVED and not _approval_is_sufficiently_corroborated(signals, intake_mode):
        return _finalise(
            session_id,
            intake_mode,
            doc_type,
            provenance,
            signals,
            score=min(score, settings.review_at),
            verdict=Verdict.REVIEW,
            tier=tier,
            fail_closed=True,
        )

    return _finalise(
        session_id,
        intake_mode,
        doc_type,
        provenance,
        signals,
        score=score,
        verdict=verdict,
        tier=tier,
        fail_closed=has_error,
    )


def _hard_reject_trigger(signals: list[LayerSignal]) -> str | None:
    """A dispositive REJECT cause other than tampered provenance (ADR-004 §7 golden rule #5).

    Any analyzer can raise a hard reject by setting ``measurements["hard_reject"] = True`` on a VALID
    signal — used for a hard cross-document identity mismatch and a known fraud-ring (pHash) reuse, where
    a single positive is dispositive and must not be diluted by clean wrapper signals (fail-closed §4).
    """
    for s in signals:
        if s.status == SignalStatus.VALID and s.measurements.get("hard_reject") is True:
            return s.reason or f"{s.name}: hard-reject trigger"
    return None


def _reject_caused_only_by_review_only(signals: list[LayerSignal]) -> bool:
    """True iff the REJECT verdict depends on REVIEW-only (anomaly) signals (ADR-004 §7 golden rule #3).

    Recomputes the score over the NON-review-only signals: if that score is no longer in the reject band
    (or nothing else scored at all), then the reject was driven by review-only signals — which are not
    allowed to reject on their own. Anomalies route to REVIEW, never REJECT.
    """
    non_review = [s for s in signals if s.measurements.get("review_only") is not True]
    mean_susp, weight = _weighted_suspicion(non_review)
    if weight == 0.0:
        return True  # only review-only signals scored -> they alone cannot reject
    score = round(100.0 * (1.0 - mean_susp), 2)
    return score >= settings.review_at


# The cross-document/cross-source corroboration signals (Layer 6) — agreement of claims across the
# bundle/sources. A VALID, AGREEING one of these is what lets a forensic-path document be APPROVED
# (golden rule #2). Identity agreement (cross_document_consistency) and figure-level agreement
# (cross_source_corroboration, the income/employer bridge) both qualify; the set is config-driven.
def _agreeing_corroboration(signals: list[LayerSignal]) -> bool:
    """True iff a corroboration signal evaluated VALID and actually AGREES (low suspicion).

    A *disagreeing* corroboration signal is VALID too (it carries the mismatch) but must pull the
    verdict down via its suspicion, never prop an APPROVE up — so support requires suspicion at/below
    the agreement ceiling (``settings.corroboration_agreement_max``)."""
    for s in signals:
        if (
            s.status == SignalStatus.VALID
            and s.name in settings.corroboration_signals
            and s.suspicion is not None
            and s.suspicion <= settings.corroboration_agreement_max
        ):
            return True
    return False


def _contradiction_signals(signals: list[LayerSignal]) -> list[LayerSignal]:
    """Signals whose claims can contradict a verified document (ADR-004 §Layer-1 'claims still flow').

    Everything except the provenance signal itself, the PDF-only red flag (handled as a floor penalty),
    and REVIEW-only soft signals (which can never reject). These are the corroboration/rule signals that
    are allowed to pull a cryptographically-verified document down.
    """
    out: list[LayerSignal] = []
    for s in signals:
        if "provenance" in s.measurements:
            continue
        if s.measurements.get("red_flag") == "pdf_only_when_pullable":
            continue
        if s.measurements.get("review_only") is True:
            continue
        out.append(s)
    return out


def _approval_is_sufficiently_corroborated(signals: list[LayerSignal], intake_mode: Mode) -> bool:
    """Golden rule #2 (ADR-004 §7): clean rules alone are necessary but NOT sufficient to APPROVE.

    A fully recomputed-and-reprinted forgery satisfies every in-document invariant, so on the forensic
    (un-provenanced) FILE path APPROVE additionally requires cross-source corroboration — the claims must
    agree across the bundle/sources. A lone unsigned document with clean rules and no corroboration is
    indeterminate → REVIEW. (Provenance-verified documents return earlier with their own floor; CAMERA
    captures rest on the active challenge as the in-person anchor.)
    """
    if not _substantive_signal_evaluated(signals):
        return False
    if intake_mode == Mode.CAMERA:
        return True  # the active 3D challenge is the in-person anchor
    return _agreeing_corroboration(signals)


def _substantive_signal_evaluated(signals: list[LayerSignal]) -> bool:
    """True iff a *substantive* content/integrity signal actually evaluated (status VALID).

    Clean peripheral wrapper checks (PDF structure, perceptual-hash resubmission) finding nothing is
    not positive evidence the financial content is genuine — only that the container looks unremarkable.
    APPROVED requires the content itself to have been assessed (ADR-002/003; §4 fail-closed). The set
    of substantive signal names is configured in ``settings.substantive_content_signals``.
    """
    return any(
        s.status == SignalStatus.VALID and s.name in settings.substantive_content_signals for s in signals
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
