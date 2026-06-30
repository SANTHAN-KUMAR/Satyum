"""Layer-6 bundle corroboration integration tests (app/bundle.py + rules/corroboration.py).

These drive the REAL two-pass bundle path: each document's claim graph is judged by the registered
``ConsistencyRulesAnalyzer`` (financial_consistency), the bundle-level income bridge runs across the
graphs, and each document is re-aggregated WITH that corroboration injected. They prove the property the
§7 #2 change introduced and that this layer completes:

  * a clean financial bundle whose income corroborates ACROSS sources can reach APPROVE — which a
    per-document-first aggregation (every lone unsigned doc REVIEW) can never give;
  * the SAME bundle with a cross-source income mismatch is held at REVIEW (fail-closed), with the
    discrepancy surfaced;
  * a clean financial document with NO second income source to corroborate stays REVIEW — corroboration
    is necessary, not assumed.

No constant verdict satisfies the agree/mismatch pair, so it would FAIL the §3.2 litmus.
"""

from __future__ import annotations

from app.bundle import verify_bundle
from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.contracts import AnalysisContext, Mode, SignalStatus, Verdict
from app.registry import AnalyzerRegistry
from risk.audit import AuditLedger
from rules.analyzer import ConsistencyRulesAnalyzer

TS = "2026-06-28T12:00:00Z"


def _claim(subject, predicate, value, vtype, *, index=None):
    cross_read = vtype in ("Money", "Count")
    return Claim(
        subject=subject, predicate=predicate, value=str(value), value_type=vtype, index=index,
        cross_read_required=cross_read,
        provenance=ClaimProvenance(
            doc_id="d", page=0, bbox=(0.1, 0.1, 0.2, 0.05), confidence=0.92, source="test",
            cross_read_agree=True, corroborating_read=str(value),
        ),
    )


def _statement_graph(doc_id: str, salary: int) -> ClaimGraph:
    """A bank statement whose arithmetic reconciles (F1/F2/F4 pass) and whose salary credits = ``salary``."""
    claims = [
        _claim("account_1", "opening_balance", "10000", "Money"),
        _claim("transaction_1", "credit", str(salary), "Money", index=1),
        _claim("transaction_1", "description", "SALARY MAY", "Text", index=1),
        _claim("transaction_1", "running_balance", str(10000 + salary), "Money", index=1),
        _claim("transaction_2", "debit", "8000", "Money", index=2),
        _claim("transaction_2", "description", "RENT", "Text", index=2),
        _claim("transaction_2", "running_balance", str(10000 + salary - 8000), "Money", index=2),
        _claim("transaction_3", "credit", str(salary), "Money", index=3),
        _claim("transaction_3", "description", "SALARY JUN", "Text", index=3),
        _claim("transaction_3", "running_balance", str(10000 + 2 * salary - 8000), "Money", index=3),
        _claim("account_1", "closing_balance", str(10000 + 2 * salary - 8000), "Money"),
    ]
    return ClaimGraph(doc_id=doc_id, doc_type="BANK_STATEMENT", claims=claims)


def _slip_graph(doc_id: str, net_pay: int) -> ClaimGraph:
    """A salary slip whose identity holds (F6: gross - deductions == net)."""
    claims = [
        _claim("slip_1", "gross_earnings", str(net_pay + 10000), "Money"),
        _claim("slip_1", "total_deductions", "10000", "Money"),
        _claim("slip_1", "net_pay", str(net_pay), "Money"),
    ]
    return ClaimGraph(doc_id=doc_id, doc_type="SALARY_SLIP", claims=claims)


def _registry() -> AnalyzerRegistry:
    reg = AnalyzerRegistry()
    reg.register(ConsistencyRulesAnalyzer())  # judges each pre-seeded claim graph (financial_consistency)
    return reg


def _doc(session_id: str, graph: ClaimGraph) -> AnalysisContext:
    ctx = AnalysisContext(session_id=session_id, intake_mode=Mode.FILE, doc_type="financial")
    ctx.shared["claim_graph"] = graph
    return ctx


def test_corroborated_financial_bundle_can_approve():
    # statement salary credits (₹50k) == slip net pay (₹50k): the income story corroborates. Each clean
    # financial doc + agreeing cross-source corroboration -> APPROVE (the §7 #2 sufficient path).
    docs = [
        ("doc1:stmt", _doc("s1", _statement_graph("s1", 50000))),
        ("doc2:slip", _doc("s2", _slip_graph("s2", 50000))),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="bc1")
    income = next(s for s in b.corroboration if s.name == "cross_source_corroboration")
    assert income.status == SignalStatus.VALID and income.measurements["disagreeing_checks"] == []
    assert all(d.trust.verdict == Verdict.APPROVED for d in b.documents)
    assert b.bundle_verdict == Verdict.APPROVED
    assert b.bundle_score >= 85.0


def test_income_mismatch_bundle_is_held_at_review():
    # SAME clean documents, but the slip claims ₹1.2L net against ₹50k salary credits -> cross-source
    # income disagreement -> REVIEW (fail-closed), discrepancy surfaced. Discriminates against the above.
    docs = [
        ("doc1:stmt", _doc("s1", _statement_graph("s1", 50000))),
        ("doc2:slip", _doc("s2", _slip_graph("s2", 120000))),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="bc2")
    income = next(s for s in b.corroboration if s.name == "cross_source_corroboration")
    assert "monthly_take_home_agreement" in income.measurements["disagreeing_checks"]
    assert b.bundle_verdict == Verdict.REVIEW
    assert b.fail_closed is True
    assert any("income discrepancy" in r.lower() for r in b.reasons)


def test_clean_financial_doc_without_corroboration_stays_review():
    # A clean statement + a slip with NO comparable income figure (net pay absent) -> the income bridge
    # cannot form a cross-source relationship -> NOT_EVALUATED -> the statement is not corroborated ->
    # REVIEW. Corroboration is necessary for APPROVE, never assumed (the §7 #2 necessary condition).
    bare_slip = ClaimGraph(doc_id="s2", doc_type="SALARY_SLIP", claims=[
        _claim("slip_1", "gross_earnings", "60000", "Money"),
    ])
    docs = [
        ("doc1:stmt", _doc("s1", _statement_graph("s1", 50000))),
        ("doc2:slip", _doc("s2", bare_slip)),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="bc3")
    income = next(s for s in b.corroboration if s.name == "cross_source_corroboration")
    assert income.status == SignalStatus.NOT_EVALUATED
    assert b.bundle_verdict != Verdict.APPROVED


def test_corroborated_bundle_decision_is_audited():
    led = AuditLedger()
    docs = [
        ("doc1:stmt", _doc("s1", _statement_graph("s1", 50000))),
        ("doc2:slip", _doc("s2", _slip_graph("s2", 50000))),
    ]
    verify_bundle(docs, _registry(), led, TS, bundle_session_id="bc4")
    ok, broken = led.verify_chain()
    assert ok and broken is None
    kinds = [r.payload.get("kind") for r in led.records()]
    assert "bundle" in kinds  # the bundle decision is recorded, with the per-document records too
    assert len(led.records()) >= 3  # 2 documents + 1 bundle
