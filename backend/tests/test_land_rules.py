"""Discrimination tests for the land/title rule pack (rules/land.py, L2 registration window).

A deed registered within the legal window after execution PASSES; one registered too late, or BEFORE
execution, FAILS (RA 1908 s.23); a deed without a registration date is NOT_EVALUATED — never a fake pass.
The cross-document land rules (L1/L3/L6/L7) are the Layer-6 land bridge and are not asserted here.
"""

from __future__ import annotations

from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.config import settings
from rules import land
from rules.contracts import RuleStatus

GATE = settings.vlm_min_confidence


def _date(predicate, value):
    return Claim(
        subject="deed", predicate=predicate, value=value, value_type="Date",
        provenance=ClaimProvenance(doc_id="d", page=0, bbox=None, confidence=0.9, source="test"),
    )


def _deed(execution, registration) -> ClaimGraph:
    claims = []
    if execution is not None:
        claims.append(_date("execution_date", execution))
    if registration is not None:
        claims.append(_date("registration_date", registration))
    return ClaimGraph(doc_id="d", doc_type="SALE_DEED", claims=claims)


def _l2(graph):
    results = land.evaluate(graph, min_confidence=GATE, tolerance=1.0)
    return next(r for r in results if r.rule_id == "L2")


def test_l2_registration_within_window_passes():
    assert _l2(_deed("2020-01-01", "2020-03-15")).status == RuleStatus.PASS


def test_l2_registration_after_window_fails():
    # registered ~7 months after execution — past the 4-month statutory window.
    assert _l2(_deed("2020-01-01", "2020-08-01")).status == RuleStatus.FAIL


def test_l2_registration_before_execution_fails():
    # a registration that PRECEDES execution is impossible — a backdating/title defect.
    assert _l2(_deed("2020-06-01", "2020-01-01")).status == RuleStatus.FAIL


def test_l2_discriminates_window():
    good = _l2(_deed("2020-01-01", "2020-02-01"))
    bad = _l2(_deed("2020-01-01", "2020-09-01"))
    assert good.status == RuleStatus.PASS and bad.status == RuleStatus.FAIL


def test_l2_not_evaluated_without_registration_date():
    assert _l2(_deed("2020-01-01", None)).status == RuleStatus.NOT_EVALUATED


def test_land_pack_routes_only_deed_types():
    # a non-deed land type is not handled by the single-document pack (cross-doc -> Layer-6 bridge).
    results = land.evaluate(_deed("2020-01-01", "2020-03-01"), min_confidence=GATE, tolerance=1.0)
    assert [r.rule_id for r in results] == ["L2"]
