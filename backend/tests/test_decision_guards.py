"""Property tests for the Layer-7 golden-rule guards (ADR-004 §7).

These encode the decision-brain invariants as discrimination tests — each would FAIL if its guard were
removed (CLAUDE.md §3.2):

  * a hard-reject trigger (fraud-ring reuse / hard identity mismatch) REJECTS, fail-closed, even amid
    otherwise-clean signals — and only when raised on a VALID signal;
  * a REVIEW-only signal (anomaly intelligence) can NEVER, on its own, drive a REJECT — it routes to
    REVIEW, while a genuine non-review reject is left untouched.
"""

from __future__ import annotations

from app.contracts import LayerSignal, Mode, SignalStatus, Verdict
from risk.engine import aggregate


def _valid(name, suspicion, *, weight=0.4, measurements=None):
    return LayerSignal(
        name=name,
        layer=3,
        mode=Mode.FILE,
        status=SignalStatus.VALID,
        suspicion=suspicion,
        weight=weight,
        reason="x",
        measurements=measurements or {},
    )


# --- golden rule #5: hard-reject triggers are dispositive -----------------------------------------


def test_hard_reject_trigger_rejects_even_amid_clean_signals():
    clean = _valid("financial_consistency", 0.0)
    fraud = _valid("phash_resubmission", 0.95, measurements={"hard_reject": True})
    ts = aggregate("s", Mode.FILE, [clean, fraud])
    assert ts.verdict == Verdict.REJECTED and ts.fail_closed


def test_hard_reject_is_the_discriminator():
    """Same two signals; only the hard_reject flag differs → REJECT vs (non-reject). Fails a constant."""
    clean = _valid("financial_consistency", 0.0)
    flagged = aggregate("s", Mode.FILE, [clean, _valid("phash", 0.0, measurements={"hard_reject": True})])
    unflagged = aggregate("s", Mode.FILE, [clean, _valid("phash", 0.0)])
    assert flagged.verdict == Verdict.REJECTED
    # without the flag, clean arithmetic alone (no corroboration) is REVIEW, not REJECT (§7 #2)
    assert unflagged.verdict == Verdict.REVIEW


def test_hard_reject_only_honoured_on_valid_signals():
    """A hard_reject flag on a non-VALID signal is ignored (it carries no measured evidence)."""
    clean = _valid("financial_consistency", 0.0)
    ne = LayerSignal.not_evaluated("x", 3, Mode.FILE, "n/a", hard_reject=True)
    ts = aggregate("s", Mode.FILE, [clean, ne])
    assert ts.verdict != Verdict.REJECTED  # the NOT_EVALUATED flag did not trigger a reject


# --- golden rule #3: anomalies (REVIEW-only) can never reject -------------------------------------


def test_review_only_signal_cannot_reject_alone():
    """A REVIEW-only signal whose suspicion would otherwise reject is downgraded to REVIEW."""
    anomaly = _valid("anomaly_intelligence", 0.95, measurements={"review_only": True})
    ts = aggregate("s", Mode.FILE, [anomaly])
    assert ts.verdict == Verdict.REVIEW and ts.fail_closed
    assert ts.trust_score >= 60  # gauge pulled to the REVIEW band to agree with the verdict


def test_review_only_flag_is_the_discriminator():
    """The same high-suspicion signal rejects WITHOUT the review_only flag, only reviews WITH it."""
    with_flag = aggregate("s", Mode.FILE, [_valid("a", 0.95, measurements={"review_only": True})])
    without = aggregate("s", Mode.FILE, [_valid("a", 0.95)])
    assert with_flag.verdict == Verdict.REVIEW
    assert without.verdict == Verdict.REJECTED


def test_genuine_non_review_reject_is_untouched_by_the_anomaly_guard():
    """A real tamper (non-review) still REJECTS even with a review-only anomaly also present."""
    tamper = _valid("financial_consistency", 0.95)
    anomaly = _valid("anomaly_intelligence", 0.40, weight=0.1, measurements={"review_only": True})
    ts = aggregate("s", Mode.FILE, [tamper, anomaly])
    assert ts.verdict == Verdict.REJECTED


def test_capped_anomaly_with_clean_content_does_not_reject():
    """An at-cap anomaly (0.40) alongside clean content routes to APPROVE/REVIEW, never REJECT."""
    clean = _valid("financial_consistency", 0.0, weight=0.4)
    anomaly = _valid("anomaly_intelligence", 0.40, weight=0.1, measurements={"review_only": True})
    ts = aggregate("s", Mode.FILE, [clean, anomaly])
    assert ts.verdict != Verdict.REJECTED


# --- ADR-004 §Layer-1: verified = byte-authenticity, not claim-truthfulness -----------------------


def _verified():
    return LayerSignal(
        name="signature",
        layer=1,
        mode=Mode.FILE,
        status=SignalStatus.VALID,
        suspicion=0.0,
        weight=0.0,
        reason="valid PAdES",
        measurements={"provenance": "verified", "method": "PAdES"},
    )


def test_verified_floor_is_pulled_down_by_a_corroboration_mismatch():
    """A cryptographically signed document does NOT short-circuit to clean: a corroboration mismatch
    (its claims contradict another source) pulls the verified floor down. Would FAIL against the old
    engine that returned ~99/APPROVED for any verified document regardless of its claims."""
    clean = aggregate("s", Mode.FILE, [_verified()])
    contradicted = aggregate(
        "s", Mode.FILE, [_verified(), _valid("cross_document_consistency", 0.92, weight=0.5)]
    )
    assert clean.verdict == Verdict.APPROVED
    assert contradicted.verdict != Verdict.APPROVED
    assert contradicted.trust_score < clean.trust_score


def test_verified_with_agreeing_corroboration_stays_approved():
    """Claims flow, but when they AGREE the verified document keeps its high floor → APPROVED."""
    ts = aggregate("s", Mode.FILE, [_verified(), _valid("cross_document_consistency", 0.0, weight=0.5)])
    assert ts.verdict == Verdict.APPROVED
