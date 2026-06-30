"""Tests for the claimed-vs-document PAN cross-check (catches a tampered/mismatched applicant PAN)."""

from __future__ import annotations

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.claimed_identity import ClaimedIdentityAnalyzer
from forensics.entities import ExtractedEntities


def _ctx(claimed_pan: str | None, doc_pan: str | None) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE)
    if claimed_pan is not None:
        ctx.claimed_identity = {"pan": claimed_pan}
    if doc_pan is not None:
        ctx.shared["entities"] = ExtractedEntities(pan=doc_pan)
    return ctx


def test_matching_pan_is_clean():
    sig = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "ABCPK1234L"))
    assert sig.status == SignalStatus.VALID and sig.suspicion == 0.0
    assert sig.measurements["claimed_pan_matches_document"] is True


def test_different_pan_is_flagged():
    """A genuinely different typed PAN vs the document -> identity mismatch (high suspicion)."""
    sig = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "ZZZPZ9999Z"))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion >= 0.8
    assert "does not match" in sig.reason.lower()
    assert sig.measurements["claimed_pan_matches_document"] is False


def test_one_char_difference_is_review_not_reject():
    """A single-character difference is treated as a likely OCR slip -> REVIEW band, not a hard reject."""
    sig = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "ABCPK1234X"))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and 0.0 < sig.suspicion <= 0.5


def test_discrimination_match_vs_mismatch():
    """The §3.2 litmus: matching -> 0.0, mismatching -> high; no constant satisfies both."""
    good = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "ABCPK1234L"))
    bad = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "MNOPQ5678R"))
    assert good.suspicion == 0.0 and bad.suspicion is not None and bad.suspicion > good.suspicion


def test_no_claim_is_not_applicable():
    az = ClaimedIdentityAnalyzer()
    assert az.applicable(_ctx(None, "ABCPK1234L")) is False


def test_document_without_pan_is_not_evaluated():
    sig = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", None))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_malformed_claimed_pan_is_not_evaluated():
    sig = ClaimedIdentityAnalyzer().analyze(_ctx("NOTAPAN", "ABCPK1234L"))
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_applicable_only_when_claimed_pan_present_on_file_intake():
    az = ClaimedIdentityAnalyzer()
    assert az.applicable(_ctx("ABCPK1234L", "ABCPK1234L")) is True
    cam = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA, claimed_identity={"pan": "ABCPK1234L"})
    assert az.applicable(cam) is False
