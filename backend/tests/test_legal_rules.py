"""Discrimination tests for the legal-contract rule pack (rules/legal.py, G1–G6).

Each rule: a genuine document PASSES, a single-edit/spliced/incomplete document FAILS (localising the
defect), and absent inputs yield NOT_EVALUATED — never a fabricated pass. The genuine/tampered pair per
rule would FAIL the §3.2 litmus against any constant. All over the template-independent claim graph.
"""

from __future__ import annotations

from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.config import settings
from rules import legal
from rules.contracts import RuleStatus

GATE = settings.vlm_min_confidence
TOL = settings.arithmetic_abs_tolerance


def _c(subject, predicate, value, vtype, *, index=None, agree=True, conf=0.9):
    cross_read = vtype in ("Money", "Count", "Integer", "Percentage", "Duration")
    return Claim(
        subject=subject, predicate=predicate, value=str(value), value_type=vtype, index=index,
        cross_read_required=cross_read,
        provenance=ClaimProvenance(
            doc_id="d", page=0, bbox=(0.1, 0.1, 0.2, 0.05), confidence=conf, source="test",
            cross_read_agree=agree, corroborating_read=str(value),
        ),
    )


def _graph(claims, doc_type="LOAN_AGREEMENT") -> ClaimGraph:
    return ClaimGraph(doc_id="d", doc_type=doc_type, claims=claims)


def _result(graph, rule_id):
    results = legal.evaluate(graph, min_confidence=GATE, tolerance=TOL)
    return next(r for r in results if r.rule_id == rule_id)


# --- G1 words = figures ---------------------------------------------------------------------------


def test_g1_words_match_figures_passes():
    g = _graph([
        _c("agreement", "consideration", "500000", "Money"),
        _c("agreement", "consideration_in_words", "Rupees Five Lakh Only", "Text"),
    ])
    assert _result(g, "G1").status == RuleStatus.PASS


def test_g1_edited_figure_breaks_words_match():
    # the figure was edited to 6,00,000 but the words still say Five Lakh — the classic tamper tell.
    g = _graph([
        _c("agreement", "consideration", "600000", "Money"),
        _c("agreement", "consideration_in_words", "Rupees Five Lakh Only", "Text"),
    ])
    r = _result(g, "G1")
    assert r.status == RuleStatus.FAIL and r.evidence


def test_g1_not_evaluated_without_words():
    g = _graph([_c("agreement", "consideration", "500000", "Money")])
    assert _result(g, "G1").status == RuleStatus.NOT_EVALUATED


def test_g1_also_checks_monetary_terms():
    g = _graph([
        _c("monetary_term_1", "kind", "principal", "Text"),
        _c("monetary_term_1", "amount", "1000000", "Money"),
        _c("monetary_term_1", "amount_in_words", "Rupees Twelve Lakh Only", "Text"),  # 12L != 10L
    ])
    assert _result(g, "G1").status == RuleStatus.FAIL


# --- G2 term arithmetic ---------------------------------------------------------------------------


def test_g2_term_arithmetic_passes():
    g = _graph([
        _c("agreement", "effective_date", "2020-01-01", "Date"),
        _c("agreement", "term", "12", "Duration"),
        _c("agreement", "end_date", "2021-01-01", "Date"),
    ])
    assert _result(g, "G2").status == RuleStatus.PASS


def test_g2_wrong_end_date_fails():
    g = _graph([
        _c("agreement", "effective_date", "2020-01-01", "Date"),
        _c("agreement", "term", "12", "Duration"),
        _c("agreement", "end_date", "2021-06-01", "Date"),  # 5 months off
    ])
    assert _result(g, "G2").status == RuleStatus.FAIL


# --- G3 party-name consistency --------------------------------------------------------------------


def test_g3_consistent_name_passes():
    g = _graph([
        _c("party_1", "name", "John A Smith", "PersonName", index=1),
        _c("party_1", "name", "John Smith", "PersonName", index=2),  # initial dropped — still matches
    ])
    assert _result(g, "G3").status == RuleStatus.PASS


def test_g3_name_drift_across_sections_fails():
    g = _graph([
        _c("party_1", "name", "John Smith", "PersonName", index=1),
        _c("party_1", "name", "Jane Doe", "PersonName", index=2),  # spliced document
    ])
    assert _result(g, "G3").status == RuleStatus.FAIL


def test_g3_single_occurrence_not_evaluated():
    g = _graph([_c("party_1", "name", "John Smith", "PersonName", index=1)])
    assert _result(g, "G3").status == RuleStatus.NOT_EVALUATED


# --- G4 schedule references resolve ---------------------------------------------------------------


def test_g4_resolved_references_pass():
    g = _graph([
        _c("clause_1", "refers_to", "Schedule A", "Text"),
        _c("schedule_1", "label", "Schedule A", "Text"),
    ])
    assert _result(g, "G4").status == RuleStatus.PASS


def test_g4_dangling_reference_fails():
    g = _graph([
        _c("clause_1", "refers_to", "Schedule B", "Text"),  # referenced but never defined
        _c("schedule_1", "label", "Schedule A", "Text"),
    ])
    assert _result(g, "G4").status == RuleStatus.FAIL


# --- G5 page completeness -------------------------------------------------------------------------


def test_g5_complete_pages_pass():
    g = _graph([
        _c("doc", "printed_page_number", "1", "Count", index=1),
        _c("doc", "printed_page_number", "2", "Count", index=2),
        _c("doc", "printed_page_number", "3", "Count", index=3),
        _c("agreement", "printed_page_count", "3", "Count"),
    ])
    assert _result(g, "G5").status == RuleStatus.PASS


def test_g5_missing_page_fails():
    g = _graph([
        _c("doc", "printed_page_number", "1", "Count", index=1),
        _c("doc", "printed_page_number", "3", "Count", index=2),  # page 2 removed
        _c("agreement", "printed_page_count", "3", "Count"),
    ])
    r = _result(g, "G5")
    assert r.status == RuleStatus.FAIL and "missing" in r.reason.lower()


# --- G6 execution completeness --------------------------------------------------------------------


def _exec_claims(witnesses):
    claims = [
        _c("party_1", "name", "John Smith", "PersonName", index=1),
        _c("execution_block", "signature", "John Smith", "PersonName", index=1),
        _c("execution_block", "execution_date", "2020-01-01", "Date"),
    ]
    for i, w in enumerate(witnesses, start=1):
        claims.append(_c("execution_block", "witness", w, "PersonName", index=i))
    return claims


def test_g6_complete_execution_passes():
    g = _graph(_exec_claims(["Witness One", "Witness Two"]))
    assert _result(g, "G6").status == RuleStatus.PASS


def test_g6_missing_witness_fails():
    g = _graph(_exec_claims(["Witness One"]))  # only one witness
    r = _result(g, "G6")
    assert r.status == RuleStatus.FAIL and "witness" in r.reason.lower()


def test_g6_no_execution_block_not_evaluated():
    g = _graph([_c("agreement", "consideration", "500000", "Money")])
    assert _result(g, "G6").status == RuleStatus.NOT_EVALUATED
