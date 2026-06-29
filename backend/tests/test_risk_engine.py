"""Risk-engine tests: scoring rule, fail-closed semantics, provenance short-circuits, NOT_EVALUATED
exclusion. These encode the cardinal banking rule — never a silent APPROVE."""

from __future__ import annotations

from app.contracts import LayerSignal, Mode, Verdict
from risk.engine import aggregate


def _sig_valid(name, suspicion, weight=0.4, layer=3, mode=Mode.FILE):
    return LayerSignal.valid(name, layer, mode, suspicion, weight, "x")


def test_clean_arithmetic_alone_is_review_not_approve():
    # ADR-004 §7 #2: clean rules are necessary but NOT sufficient — a fully recomputed-and-reprinted
    # forgery passes every arithmetic invariant. A lone unsigned document with no cross-source
    # corroboration and no provenance is indeterminate -> REVIEW (fail-closed), never auto-APPROVE.
    ts = aggregate("s", Mode.FILE, [_sig_valid("arithmetic_consistency", 0.0)])
    assert ts.verdict == Verdict.REVIEW and ts.fail_closed


def test_clean_arithmetic_with_corroboration_approves():
    # The sufficient path (§7 #2): substantive content AND cross-source corroboration -> APPROVE.
    ts = aggregate("s", Mode.FILE, [
        _sig_valid("arithmetic_consistency", 0.0),
        _sig_valid("cross_document_consistency", 0.0, weight=0.5),
    ])
    assert ts.verdict == Verdict.APPROVED and ts.trust_score >= 85


def test_clean_wrapper_without_content_assessment_is_review_not_approve():
    """§4 substantive-evidence gate: peripheral wrapper checks clean (structure + pHash), but the
    document CONTENT was never assessed (arithmetic NOT_EVALUATED) and no source verified ->
    indeterminate -> REVIEW, never auto-APPROVE. Would FAIL against the pre-gate engine (which scored
    this 100/APPROVED) and against any constant verdict."""
    ts = aggregate("s", Mode.FILE, [
        _sig_valid("pdf_structure_metadata", 0.0, weight=0.15),
        _sig_valid("phash_resubmission", 0.0, weight=0.15),
        LayerSignal.not_evaluated("arithmetic_consistency", 3, Mode.FILE, "statement unreadable"),
    ])
    assert ts.verdict == Verdict.REVIEW and ts.fail_closed
    assert ts.trust_score <= 60  # gauge pulled to the REVIEW band, not a contradictory high score

    # Discrimination: add a clean SUBSTANTIVE signal AND cross-source corroboration -> the same
    # wrapper-clean doc now APPROVES (§7 #2 — substantive content + corroboration is sufficient).
    approved = aggregate("s", Mode.FILE, [
        _sig_valid("pdf_structure_metadata", 0.0, weight=0.15),
        _sig_valid("arithmetic_consistency", 0.0, weight=0.40),
        _sig_valid("cross_document_consistency", 0.0, weight=0.50),
    ])
    assert approved.verdict == Verdict.APPROVED


def test_strong_tamper_rejects():
    ts = aggregate("s", Mode.FILE, [_sig_valid("arith", 0.95)])
    assert ts.verdict == Verdict.REJECTED


def test_provenance_verified_short_circuits_to_high_trust():
    sig = LayerSignal.valid("signature", 1, Mode.FILE, 0.0, 0.0, "valid PAdES",
                            measurements={"provenance": "verified", "method": "PAdES"})
    ts = aggregate("s", Mode.FILE, [sig])
    assert ts.provenance.verified and ts.tier_reached == "source-verified"
    assert ts.verdict == Verdict.APPROVED


def test_tampered_signature_hard_rejects_fail_closed():
    sig = LayerSignal.valid("signature", 1, Mode.FILE, 1.0, 0.0, "appended bytes after ByteRange",
                            measurements={"provenance": "tampered", "method": "PAdES"})
    ts = aggregate("s", Mode.FILE, [sig])
    assert ts.provenance.tampered and ts.verdict == Verdict.REJECTED and ts.fail_closed


def test_error_signal_never_approves():
    ts = aggregate("s", Mode.FILE, [_sig_valid("arith", 0.0),
                                    LayerSignal.error("ocr", 3, Mode.FILE, "boom")])
    assert ts.verdict != Verdict.APPROVED
    assert ts.fail_closed


def test_all_not_evaluated_is_review_not_approve():
    ts = aggregate("s", Mode.FILE, [
        LayerSignal.not_evaluated("a", 3, Mode.FILE, "n/a"),
        LayerSignal.not_evaluated("b", 3, Mode.FILE, "n/a"),
    ])
    assert ts.verdict == Verdict.REVIEW and ts.fail_closed


def test_not_evaluated_is_excluded_from_score():
    # Adding a NOT_EVALUATED signal must NOT change the score (excluded from numerator and denominator).
    base = aggregate("s", Mode.FILE, [_sig_valid("arith", 0.2)])
    with_ne = aggregate("s", Mode.FILE, [
        _sig_valid("arith", 0.2),
        LayerSignal.not_evaluated("stego", 3, Mode.FILE, "gated"),
    ])
    assert base.trust_score == with_ne.trust_score


def test_verdict_band_agrees_with_displayed_score_at_threshold():
    """Regression: verdict and the displayed gauge must derive from the SAME (rounded) score. A
    suspicion that lands on a band edge with a float artefact (0.4 -> 0.4000000000000001 -> score
    59.999999999999986) must NOT show a REJECTED verdict beside a 60.0 gauge the UI reads as REVIEW.
    Would FAIL against the pre-fix engine (verdict from the unrounded score)."""
    ts = aggregate("s", Mode.FILE, [_sig_valid("arithmetic_consistency", 0.4, weight=0.4)])
    assert ts.trust_score == 60.0  # rounds to the band edge
    # 60.0 sits in the REVIEW band (>= review_at), so the verdict MUST be REVIEW, not REJECTED.
    assert ts.verdict == Verdict.REVIEW


def test_pdf_only_red_flag_penalises_even_when_signature_verified():
    verified = LayerSignal.valid("signature", 1, Mode.FILE, 0.0, 0.0, "ok",
                                 measurements={"provenance": "verified", "method": "PAdES"})
    flag = LayerSignal.valid("pdf_only_red_flag", 1, Mode.FILE, 0.55, 0.10, "avoided pull",
                             measurements={"red_flag": "pdf_only_when_pullable"})
    clean = aggregate("s", Mode.FILE, [verified])
    flagged = aggregate("s", Mode.FILE, [verified, flag])
    assert flagged.trust_score < clean.trust_score
