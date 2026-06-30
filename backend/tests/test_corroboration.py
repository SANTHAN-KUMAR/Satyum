"""Layer-6 cross-source corroboration discrimination tests (rules/corroboration.py).

These prove the income/employer bridge over the claim graph SEPARATES agreement from disagreement and
respects the §5.2→§6 trust handoff (only cross-read-verified claims corroborate). Each pair would FAIL
against a constant: an agreeing bundle yields near-zero suspicion + no disagreements; a mismatched one
yields a REVIEW-band suspicion + a localised disagreeing check. No fixture is hand-tuned to a verdict.
"""

from __future__ import annotations

from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.config import settings
from app.contracts import SignalStatus
from rules.corroboration import (
    ANNUAL_GROSS,
    MONTHLY_TAKE_HOME,
    _org_ratio,
    corroborate,
    cross_source_signal,
    extract_income_observations,
)

GATE = settings.vlm_min_confidence
REVIEW_CAP = round(1.0 - settings.review_at / 100.0, 2)


def _claim(subject, predicate, value, vtype, *, index=None, agree=True, conf=0.9):
    cross_read = vtype in ("Money", "Count", "Integer", "Percentage")
    return Claim(
        subject=subject, predicate=predicate, value=str(value), value_type=vtype, index=index,
        cross_read_required=cross_read,
        provenance=ClaimProvenance(
            doc_id="d", page=0, bbox=(0.1, 0.1, 0.2, 0.05), confidence=conf, source="test",
            cross_read_agree=agree, corroborating_read=str(value) if agree else "different",
        ),
    )


def _statement(doc_id, salary_amounts, *, desc="SALARY CREDIT", agree=True) -> ClaimGraph:
    claims = [_claim("account_1", "opening_balance", "10000", "Money")]
    for i, amt in enumerate(salary_amounts, start=1):
        claims.append(_claim(f"transaction_{i}", "credit", str(amt), "Money", index=i, agree=agree))
        claims.append(_claim(f"transaction_{i}", "description", f"{desc} {i}", "Text", index=i))
    return ClaimGraph(doc_id=doc_id, doc_type="BANK_STATEMENT", claims=claims)


def _slip(doc_id, net_pay, *, employer=None, agree=True) -> ClaimGraph:
    claims = [_claim("slip_1", "net_pay", str(net_pay), "Money", agree=agree)]
    if employer is not None:
        claims.append(_claim("slip_1", "employer", employer, "OrgName"))
    return ClaimGraph(doc_id=doc_id, doc_type="SALARY_SLIP", claims=claims)


def _form16(doc_id, gross_income, *, employer=None) -> ClaimGraph:
    claims = [_claim("income_1", "gross_income", str(gross_income), "Money")]
    if employer is not None:
        claims.append(_claim("income_1", "employer", employer, "OrgName"))
    return ClaimGraph(doc_id=doc_id, doc_type="FORM16", claims=claims)


# --- income agreement vs disagreement -------------------------------------------------------------


def test_income_agrees_across_statement_and_slip():
    graphs = {"stmt": _statement("s", [50000, 50000]), "slip": _slip("p", 50000)}
    sig = cross_source_signal(graphs)
    assert sig.status == SignalStatus.VALID
    assert sig.measurements["disagreeing_checks"] == []
    assert sig.suspicion is not None and sig.suspicion <= settings.corroboration_agreement_max


def test_income_mismatch_routes_to_review_band_not_reject():
    # slip claims ₹1.2L net but the account only receives ₹40k salary credits — a strong, explainable
    # tell. It must land in the REVIEW band (a human reconciles), never an auto-reject on its own.
    graphs = {"stmt": _statement("s", [40000, 40000]), "slip": _slip("p", 120000)}
    sig = cross_source_signal(graphs)
    assert sig.status == SignalStatus.VALID
    assert "monthly_take_home_agreement" in sig.measurements["disagreeing_checks"]
    assert sig.suspicion == REVIEW_CAP  # capped to REVIEW — figure corroboration never rejects alone


def test_income_signal_discriminates_agree_from_mismatch():
    agree = cross_source_signal({"stmt": _statement("s", [50000]), "slip": _slip("p", 50000)})
    mismatch = cross_source_signal({"stmt": _statement("s", [50000]), "slip": _slip("p", 90000)})
    # would FAIL against a constant: the same shape, only the figure differs, flips the suspicion band
    assert agree.suspicion is not None and mismatch.suspicion is not None
    assert mismatch.suspicion > agree.suspicion


def test_annualised_take_home_exceeding_gross_is_a_contradiction():
    # slip net ₹1L/mo -> ₹12L/yr take-home, but Form-16 gross is ₹5L: impossible (net > gross).
    graphs = {"slip": _slip("p", 100000), "f16": _form16("f", 500000)}
    sig = cross_source_signal(graphs)
    assert sig.status == SignalStatus.VALID
    assert "annual_income_floor" in sig.measurements["disagreeing_checks"]


def test_gross_legitimately_exceeding_net_is_not_flagged():
    # gross ₹12L/yr, net ₹70k/mo (-> ₹8.4L take-home): gross > net is normal (tax/PF). No disagreement.
    graphs = {"slip": _slip("p", 70000), "f16": _form16("f", 1200000)}
    sig = cross_source_signal(graphs)
    assert sig.status == SignalStatus.VALID
    assert sig.measurements["disagreeing_checks"] == []


# --- the §5.2 -> §6 trust handoff -----------------------------------------------------------------


def test_only_cross_read_verified_claims_corroborate():
    # The slip's net_pay FAILED the OCR cross-read (a laundered/unreadable figure). It must be EXCLUDED,
    # leaving a single income source -> NOT_EVALUATED, never silently corroborated against the statement.
    graphs = {"stmt": _statement("s", [50000]), "slip": _slip("p", 50000, agree=False)}
    sig = cross_source_signal(graphs)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.measurements["income_sources"] == 1  # only the statement survived the trust gate


def test_low_confidence_income_is_not_trusted():
    graphs = {
        "stmt": _statement("s", [50000]),
        "slip": ClaimGraph(doc_id="p", doc_type="SALARY_SLIP", claims=[
            _claim("slip_1", "net_pay", "50000", "Money", conf=GATE - 0.1),
        ]),
    }
    assert cross_source_signal(graphs).status == SignalStatus.NOT_EVALUATED


# --- observation extraction (narration gate) ------------------------------------------------------


def test_salary_credit_requires_narration_match():
    # credits exist but none read as salary (all "REFUND") -> the statement yields NO income observation.
    obs = extract_income_observations({"stmt": _statement("s", [50000, 50000], desc="REFUND")})
    assert obs == []


def test_representative_salary_is_robust_median_not_a_one_off_spike():
    # a one-off arrears spike (200000) must not move the representative monthly figure off 50000.
    obs = extract_income_observations({"stmt": _statement("s", [50000, 200000, 50000])})
    assert len(obs) == 1 and obs[0].kind == MONTHLY_TAKE_HOME
    assert str(obs[0].amount) == "50000"


def test_single_source_is_not_evaluated_never_a_fake_pass():
    assert cross_source_signal({"stmt": _statement("s", [50000])}).status == SignalStatus.NOT_EVALUATED


# --- employer agreement ---------------------------------------------------------------------------


def test_employer_agreement_tolerates_legal_suffix_variants():
    graphs = {
        "slip": _slip("p", 50000, employer="Infosys Ltd"),
        "f16": _form16("f", 700000, employer="INFOSYS LIMITED"),
    }
    sig = cross_source_signal(graphs)
    assert sig.measurements["employer_checked"] is True
    assert "employer_agreement" not in sig.measurements["disagreeing_checks"]


def test_employer_mismatch_is_a_soft_disagreement():
    graphs = {
        "slip": _slip("p", 50000, employer="Infosys Ltd"),
        "f16": _form16("f", 700000, employer="Wipro Limited"),
    }
    sig = cross_source_signal(graphs)
    assert "employer_agreement" in sig.measurements["disagreeing_checks"]


def test_org_ratio_separates_same_from_different():
    assert _org_ratio("Infosys Ltd", "INFOSYS LIMITED") == 1.0
    assert _org_ratio("Infosys", "Wipro") < settings.income_employer_min_ratio


def test_corroborate_returns_observations_and_kinds():
    result = corroborate({"slip": _slip("p", 50000), "f16": _form16("f", 700000)})
    kinds = {o.kind for o in result.observations}
    assert kinds == {MONTHLY_TAKE_HOME, ANNUAL_GROSS}
