"""Tests for the Stage-3 rule loop (PROPOSAL-001 §6.3.1).

The miner tests are the honesty proof (CLAUDE.md §3.1/§3.2): the miner discovers a REAL discriminating
conjunction from labelled data with measured metrics, and finds NOTHING in patternless data. The
analyzer tests prove an approved rule fires as an explainable deterministic signal citing the approver.
"""

from __future__ import annotations

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from rule_mining.analyzer import PromotedRuleAnalyzer
from rule_mining.miner import LabeledCase, mine_rules
from rule_mining.model import CandidateRule, Predicate, RuleStatus
from rule_mining.store import RuleNotFoundError, RuleStore


# --- predicate + rule evaluation -----------------------------------------------------------------

def test_predicate_ops_and_missing_feature():
    assert Predicate("x", "lt", 5).matches({"x": 3}) is True
    assert Predicate("x", "lt", 5).matches({"x": 9}) is False
    assert Predicate("x", "ge", 5).matches({"x": 5}) is True
    assert Predicate("h", "in", (2, 3, 4)).matches({"h": 3}) is True
    assert Predicate("missing", "lt", 5).matches({"x": 1}) is False  # fail-safe on absent feature


def test_rule_fires_is_a_conjunction():
    rule = CandidateRule("R1", (Predicate("a", "lt", 5), Predicate("b", "ge", 100)),
                         "t", 0.8, 0.5, 0.9, 4.0, "test")
    assert rule.fires({"a": 3, "b": 200}) is True
    assert rule.fires({"a": 3, "b": 50}) is False
    # an empty rule never fires (fail-safe)
    assert CandidateRule("R0", (), "t", 0.5, 0, 0, 0, "test").fires({"a": 1}) is False


# --- the miner: real discrimination --------------------------------------------------------------

def _fraud_dataset() -> list[LabeledCase]:
    """A dataset where fraud is the conjunction (high loan ∧ night submission), with confounders that
    defeat any SINGLE feature — so the miner must induce a conjunction to separate them."""
    cases: list[LabeledCase] = []
    # 20 fraud: high loan + night submission + new employer
    for i in range(20):
        cases.append(LabeledCase({"employer_age_months": 1 + i % 5, "loan_amount": 2_500_000,
                                   "submit_hour": 2}, True))
    # 40 genuine: established, low loan, daytime
    for _ in range(40):
        cases.append(LabeledCase({"employer_age_months": 60, "loan_amount": 500_000,
                                  "submit_hour": 11}, False))
    # 25 genuine: night submission + new employer but LOW loan (defeats submit_hour / employer alone)
    for _ in range(25):
        cases.append(LabeledCase({"employer_age_months": 3, "loan_amount": 300_000,
                                  "submit_hour": 2}, False))
    # 15 genuine: high loan but established + daytime (defeats loan alone)
    for _ in range(15):
        cases.append(LabeledCase({"employer_age_months": 70, "loan_amount": 2_600_000,
                                  "submit_hour": 14}, False))
    return cases


def test_miner_discovers_the_real_conjunction():
    rules = mine_rules(_fraud_dataset(), threat_class="salary_ring", min_confidence=0.8)
    assert rules, "the miner must discover the planted conjunction"
    top = rules[0]
    # Measured metrics are real (the planted pattern is perfectly separable by a conjunction).
    assert top.confidence >= 0.8
    assert top.support >= 0.5
    # It must actually separate: fires on a fraud-like case, NOT on the confounder groups.
    assert top.fires({"employer_age_months": 2, "loan_amount": 2_500_000, "submit_hour": 2}) is True
    assert top.fires({"employer_age_months": 3, "loan_amount": 300_000, "submit_hour": 2}) is False
    assert top.fires({"employer_age_months": 70, "loan_amount": 2_600_000, "submit_hour": 14}) is False
    assert top.fires({"employer_age_months": 60, "loan_amount": 500_000, "submit_hour": 11}) is False


def test_miner_finds_nothing_in_patternless_data():
    """Labels uncorrelated with features -> no rule clears confidence/support (real, not a constant)."""
    cases = []
    for i in range(40):
        # feature varies, but fraud is the first 10 regardless of the feature value -> no separation
        cases.append(LabeledCase({"amt": (i % 4) * 100}, is_fraud=i < 10))
    assert mine_rules(cases, min_confidence=0.8) == []


def test_miner_reports_measured_metrics_not_invented():
    rules = mine_rules(_fraud_dataset(), min_confidence=0.8)
    top = rules[0]
    # Recompute confidence directly and compare to the reported value (no invented numbers, §3.3).
    cases = _fraud_dataset()
    n_match = sum(1 for c in cases if top.fires(c.features))
    n_fraud = sum(1 for c in cases if top.fires(c.features) and c.is_fraud)
    assert abs(top.confidence - n_fraud / n_match) < 1e-6


# --- store lifecycle -----------------------------------------------------------------------------

def test_store_approval_deploys_only_approved_rules():
    store = RuleStore()
    r1 = CandidateRule("R1", (Predicate("a", "lt", 5),), "t", 0.8, 0.5, 0.9, 4.0, "x")
    r2 = CandidateRule("R2", (Predicate("b", "ge", 9),), "t", 0.7, 0.5, 0.9, 4.0, "x")
    store.add_candidates([r1, r2])
    assert store.deployed_rules() == []  # candidates are not deployed until approved
    store.approve("R1", approved_by="A. Rao", decided_at="2026-06-30T00:00:00Z")
    deployed = store.deployed_rules()
    assert len(deployed) == 1 and deployed[0].rule.rule_id == "R1"
    assert deployed[0].approved_by == "A. Rao"
    store.reject("R2", approved_by="A. Rao", decided_at="t")
    assert len(store.deployed_rules()) == 1  # rejected never deploys


def test_store_unknown_rule_raises():
    with pytest.raises(RuleNotFoundError):
        RuleStore().approve("nope", approved_by="x", decided_at="t")


# --- analyzer: an approved rule fires as an explainable deterministic signal ----------------------

def _ctx(features: dict) -> AnalysisContext:
    return AnalysisContext(session_id="t", intake_mode=Mode.FILE, features=features)


def test_analyzer_fires_approved_rule_with_explanation():
    store = RuleStore()
    rule = CandidateRule("R-2026-014", (Predicate("loan_amount", "ge", 1_500_000),
                                        Predicate("submit_hour", "lt", 6)),
                         "salary_ring", 0.85, 1.0, 1.0, 5.0, "federated rule mining PoC")
    store.add_candidate(rule)
    store.approve("R-2026-014", approved_by="A. Rao", decided_at="2026-06-30T00:00:00Z")
    az = PromotedRuleAnalyzer(store=store)

    sig = az.analyze(_ctx({"loan_amount": 2_500_000, "submit_hour": 2}))
    assert sig.status == SignalStatus.VALID and sig.suspicion == 0.85
    assert "R-2026-014" in sig.reason and "A. Rao" in sig.reason  # admissible: rule id + approver
    assert sig.measurements["fired"][0]["rule_id"] == "R-2026-014"


def test_analyzer_clean_when_no_rule_matches():
    store = RuleStore()
    rule = CandidateRule("R1", (Predicate("loan_amount", "ge", 1_500_000),), "t", 0.8, 1, 1, 5, "x")
    store.add_candidate(rule)
    store.approve("R1", approved_by="A", decided_at="t")
    sig = PromotedRuleAnalyzer(store=store).analyze(_ctx({"loan_amount": 100_000}))
    assert sig.status == SignalStatus.VALID and sig.suspicion == 0.0


def test_analyzer_not_evaluated_without_features_or_rules():
    store = RuleStore()
    # no deployed rules -> NOT_EVALUATED
    assert PromotedRuleAnalyzer(store=store).analyze(_ctx({"x": 1})).status == SignalStatus.NOT_EVALUATED
    # deployed rule but no features -> NOT_EVALUATED
    rule = CandidateRule("R1", (Predicate("x", "lt", 5),), "t", 0.8, 1, 1, 5, "x")
    store.add_candidate(rule); store.approve("R1", approved_by="A", decided_at="t")
    assert PromotedRuleAnalyzer(store=store).analyze(_ctx({})).status == SignalStatus.NOT_EVALUATED


def test_analyzer_applicable_requires_features_and_deployed_rules():
    store = RuleStore()
    az = PromotedRuleAnalyzer(store=store)
    assert az.applicable(_ctx({"x": 1})) is False  # no deployed rules
    rule = CandidateRule("R1", (Predicate("x", "lt", 5),), "t", 0.8, 1, 1, 5, "x")
    store.add_candidate(rule); store.approve("R1", approved_by="A", decided_at="t")
    assert az.applicable(_ctx({"x": 1})) is True
    assert az.applicable(_ctx({})) is False  # no features
