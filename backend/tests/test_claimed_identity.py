"""Tests for the claimed-vs-document identity cross-check (catches a tampered/mismatched applicant PAN,
and — the fallback fix below — a mismatched applicant NAME on a document that carries no PAN at all).
"""

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


def _ctx_name(
    claimed_pan: str | None, claimed_name: str | None, doc_pan: str | None, doc_name: str | None
) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE)
    claimed: dict[str, str] = {}
    if claimed_pan is not None:
        claimed["pan"] = claimed_pan
    if claimed_name is not None:
        claimed["name"] = claimed_name
    ctx.claimed_identity = claimed
    if doc_pan is not None or doc_name is not None:
        ctx.shared["entities"] = ExtractedEntities(pan=doc_pan, name=doc_name)
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


# --- name fallback: the confirmed identity-verification bypass this closes ------------------------
#
# MUST-FAIL FIXTURES: before this fix, a document with no extractable PAN (a land deed, an
# encumbrance certificate, or any document the extraction schema doesn't define a PAN field for)
# gated the WHOLE analyzer to NOT_EVALUATED — even when the applicant's claimed name and the
# document's own party name were two completely different people. Every test in this section would
# FAIL (status stays NOT_EVALUATED, no suspicion at all) against the pre-fix code.


def test_applicable_with_only_a_claimed_name_no_pan():
    """The gap: previously `applicable()` required a claimed PAN — a name-only claim (the only
    identity info available when onboarding never collected/sent a PAN) was invisible to this
    analyzer entirely, never even reaching analyze()."""
    az = ClaimedIdentityAnalyzer()
    ctx = _ctx_name(None, "Karnala Vamsi Krishna", None, "KARNALA VAMSI KRISHNA")
    assert az.applicable(ctx) is True


def test_name_only_mismatch_is_flagged_when_document_has_no_pan():
    """THE confirmed bypass: a land deed with no PAN, claimed name totally different from the
    document's own party name — must be flagged (soft), not silently pass with zero suspicion."""
    ctx = _ctx_name(None, "Karnala Vamsi Krishna", None, "SAI VAGDEVI EDUCATIONAL SOCIETY")
    sig = ClaimedIdentityAnalyzer().analyze(ctx)
    assert sig.status == SignalStatus.VALID  # evaluated — NOT a silent NOT_EVALUATED skip
    assert sig.suspicion is not None and sig.suspicion > 0.0
    assert sig.measurements["claimed_name_matches_document"] is False


def test_name_only_match_is_clean_when_document_has_no_pan():
    ctx = _ctx_name(None, "Karnala Vamsi Krishna", None, "KARNALA VAMSI KRISHNA")
    sig = ClaimedIdentityAnalyzer().analyze(ctx)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.measurements["claimed_name_matches_document"] is True


def test_name_comparison_is_case_insensitive_and_tolerates_initials():
    """The claimed name is normalised the same way the document side already is — an applicant typing
    mixed case, or an initial for a middle name, must not manufacture a false mismatch."""
    ctx = _ctx_name(None, "karnala vamsi krishna", None, "KARNALA V KRISHNA")
    sig = ClaimedIdentityAnalyzer().analyze(ctx)
    assert sig.suspicion == 0.0


def test_name_mismatch_severity_is_capped_soft_never_hard_reject():
    """Names are noisy by design (CLAUDE.md) — even a clear mismatch must stay in the soft/REVIEW
    band, well below a hard PAN mismatch's severity, and the reason must say so."""
    pan_bad = ClaimedIdentityAnalyzer().analyze(_ctx("ABCPK1234L", "ZZZPZ9999Z"))
    name_bad = ClaimedIdentityAnalyzer().analyze(
        _ctx_name(None, "Karnala Vamsi Krishna", None, "SAI VAGDEVI EDUCATIONAL SOCIETY")
    )
    assert pan_bad.suspicion is not None and name_bad.suspicion is not None
    assert name_bad.suspicion < pan_bad.suspicion  # a soft signal, not equivalent to a hard PAN fail
    assert "soft signal" in name_bad.reason.lower() or "manual review" in name_bad.reason.lower()


def test_pan_still_authoritative_when_both_pan_and_name_are_claimed():
    """A PAN match is not undercut by an unrelated name mismatch — PAN stays the authoritative,
    unchanged signal when both sides have one (this analyzer's original, still-correct behaviour)."""
    ctx = _ctx_name("ABCPK1234L", "Some Random Name", "ABCPK1234L", "A COMPLETELY DIFFERENT NAME")
    sig = ClaimedIdentityAnalyzer().analyze(ctx)
    assert sig.suspicion == 0.0  # PAN agreement wins; name is not consulted when PAN is present
    assert sig.measurements["claimed_pan_matches_document"] is True


def test_neither_pan_nor_name_comparable_is_not_evaluated():
    """Genuinely nothing to compare (e.g. extraction found neither field) — honestly NOT_EVALUATED,
    never a fabricated pass, and distinct from the fixed silent-skip bug above."""
    ctx = _ctx_name(None, "Karnala Vamsi Krishna", None, None)
    sig = ClaimedIdentityAnalyzer().analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED
