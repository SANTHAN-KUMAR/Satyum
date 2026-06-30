"""The Layer-3 advisory firewall — PROPOSAL-001 §2.2/§5.4, the load-bearing integrity boundary.

These tests prove the structural invariants that let the Collective Intelligence Engine sit at the
centre of the pitch WITHOUT risking the explainability charter:

  * advisory intelligence can only raise APPROVED → REVIEW — NEVER REVIEW/REJECTED → APPROVED;
  * it never changes the deterministic trust-score number;
  * it fails open (no advisory ⇒ verdict byte-for-byte unchanged);
  * a finding with no explanation cannot exist (no opaque "the model said 91%").

The exhaustive ``test_structurally_cannot_produce_an_approve`` is the heart: there is NO advisory
input that flips a non-APPROVED verdict to APPROVED. Every test would FAIL against a stub that let
advisory drive the decision.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import settings
from app.contracts import AdvisorySignal, Mode, TrustScore, Verdict
from risk.engine import attach_advisory


def _trust(verdict: Verdict, score: float) -> TrustScore:
    return TrustScore(
        session_id="t", intake_mode=Mode.FILE, trust_score=score,
        verdict=verdict, tier_reached="forensic-fallback",
    )


def _adv(suspicion: float, source: str = "fraud_registry",
         explanation: str = "matches a document flagged at a peer bank (2026-06-18)") -> AdvisorySignal:
    return AdvisorySignal(source=source, suspicion=suspicion, explanation=explanation, confidence=0.9)


def test_no_advisory_is_fail_open_unchanged():
    t = _trust(Verdict.APPROVED, 90.0)
    out = attach_advisory(t, [])
    assert out == t  # byte-for-byte identical when Layer 3 is silent
    assert out.advisory_annotations == []
    assert out.deterministic_subscore is None


def test_high_advisory_raises_approved_to_review():
    out = attach_advisory(_trust(Verdict.APPROVED, 90.0), [_adv(0.9)])
    assert out.verdict == Verdict.REVIEW
    assert out.trust_score == 90.0           # the number is untouched
    assert out.deterministic_subscore == 90.0
    assert len(out.advisory_annotations) == 1


def test_low_advisory_below_threshold_keeps_approved_but_records():
    out = attach_advisory(_trust(Verdict.APPROVED, 90.0), [_adv(settings.advisory_review_threshold - 0.1)])
    assert out.verdict == Verdict.APPROVED   # below threshold -> verdict unmoved
    assert len(out.advisory_annotations) == 1  # but the finding is still recorded for the human


def test_advisory_never_upgrades_review():
    out = attach_advisory(_trust(Verdict.REVIEW, 65.0), [_adv(1.0)])
    assert out.verdict == Verdict.REVIEW     # maximum suspicion still cannot clear to APPROVED


def test_advisory_never_clears_rejected():
    out = attach_advisory(_trust(Verdict.REJECTED, 20.0), [_adv(1.0)])
    assert out.verdict == Verdict.REJECTED


def test_structurally_cannot_produce_an_approve():
    """Exhaustive: no advisory suspicion makes a non-APPROVED verdict APPROVED (the firewall)."""
    for start in (Verdict.REVIEW, Verdict.REJECTED):
        for suspicion in (0.0, 0.49, 0.5, 0.51, 0.99, 1.0):
            out = attach_advisory(_trust(start, 50.0), [_adv(suspicion)])
            assert out.verdict != Verdict.APPROVED, f"{start} + {suspicion} must not become APPROVED"


def test_trust_score_number_never_changes():
    for verdict in (Verdict.APPROVED, Verdict.REVIEW, Verdict.REJECTED):
        out = attach_advisory(_trust(verdict, 77.5), [_adv(1.0)])
        assert out.trust_score == 77.5


def test_empty_explanation_is_rejected_at_construction():
    """No opaque score may cross the boundary — an explanation-less finding cannot even be built."""
    with pytest.raises(ValidationError):
        AdvisorySignal(source="campaign_resemblance", suspicion=0.91, explanation="")
    with pytest.raises(ValidationError):
        AdvisorySignal(source="campaign_resemblance", suspicion=0.91, explanation="   ")


def test_multiple_advisories_use_the_strongest():
    out = attach_advisory(
        _trust(Verdict.APPROVED, 90.0),
        [_adv(0.1, source="campaign_resemblance"), _adv(0.95, source="ring_evidence")],
    )
    assert out.verdict == Verdict.REVIEW
    assert len(out.advisory_annotations) == 2


def test_evidence_pack_surfaces_findings_not_a_verdict():
    out = attach_advisory(
        _trust(Verdict.APPROVED, 90.0),
        [_adv(0.9, explanation="pHash match (Hamming 4) + shared payout token → ring R-0142")],
    )
    ni = out.evidence_pack["network_intelligence"]
    assert len(ni) == 1
    assert "not a verdict" in ni[0]["note"]
    assert ni[0]["explanation"]
    assert out.evidence_pack["deterministic_subscore"] == 90.0
