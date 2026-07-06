"""Adversarial tests for Layer 4 — the deterministic financial rule pack over the claim graph.

Proves the rehomed crown jewel discriminates on the canonical claim graph (not the old StatementData):
a genuine statement passes every invariant; a single edited figure breaks an invariant and localizes
the exact cell; and — the Layer-2→Layer-4 trust handoff (ADR-004 §5.2) — a figure that failed the OCR
cross-read is treated as *missing*, yielding NOT_EVALUATED, never a fabricated pass or a false tamper.
Every test would FAIL against a constant return (CLAUDE.md §3.2).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.contracts import AnalysisContext, Mode, SignalStatus
from rules import checks, engine
from rules.analyzer import ConsistencyRulesAnalyzer
from rules.contracts import RuleStatus
from rules.financial import evaluate

GATE = 0.5
TOL = Decimal("1.0")


def _money(subject, predicate, value, *, index=None, agree=True, conf=0.9) -> Claim:
    return Claim(
        subject=subject,
        predicate=predicate,
        value=str(value),
        value_type="Money",
        index=index,
        cross_read_required=True,
        provenance=ClaimProvenance(
            doc_id="d", confidence=conf, source="vlm:x", cross_read_agree=agree, bbox=(1, 2, 3, 4)
        ),
    )


def _money_at(subject, predicate, value, *, index, bbox, agree=True, conf=0.9) -> Claim:
    """Like ``_money`` but with a caller-chosen bbox — for tests that need real column geometry."""
    return Claim(
        subject=subject,
        predicate=predicate,
        value=str(value),
        value_type="Money",
        index=index,
        cross_read_required=True,
        provenance=ClaimProvenance(
            doc_id="d", confidence=conf, source="vlm:x", cross_read_agree=agree, bbox=bbox
        ),
    )


def _date(subject, value, index) -> Claim:
    return Claim(
        subject=subject,
        predicate="posted_on",
        value=value,
        value_type="Date",
        index=index,
        cross_read_required=False,
        provenance=ClaimProvenance(doc_id="d", confidence=0.9, source="vlm:x", bbox=(0, 0, 1, 1)),
    )


def _statement(*, row1_balance="1300.00", closing="1300.00", total_debits="200.00", agree=True, dates=None):
    """A 2-row statement: open 1000, +500 → 1500, −200 → row1_balance, close 1300."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    g.add(_money("account", "opening_balance", "1000.00"))
    g.add(_money("account", "closing_balance", closing))
    g.add(_money("transaction_0", "credit", "500.00", index=0))
    g.add(_money("transaction_0", "running_balance", "1500.00", index=0))
    g.add(_money("transaction_1", "debit", "200.00", index=1))
    g.add(_money("transaction_1", "running_balance", row1_balance, index=1, agree=agree))
    g.add(_money("summary", "total_debits", total_debits))
    g.add(_money("summary", "total_credits", "500.00"))
    if dates:
        g.add(_date("transaction_0", dates[0], 0))
        g.add(_date("transaction_1", dates[1], 1))
    return g


def _status_map(graph) -> dict[str, str]:
    return {r.rule_id: str(r.status) for r in evaluate(graph, min_confidence=GATE, tolerance=1.0)}


def _rule(graph, rule_id):
    return next(r for r in evaluate(graph, min_confidence=GATE, tolerance=1.0) if r.rule_id == rule_id)


# Column x-positions for the geometric baseline tests below: a typical statement lays credit and debit
# amounts out in their own vertical band — these are just two well-separated pixel x-coordinates, not a
# calibrated/bank-specific constant (the check itself never hardcodes a position; it only ever compares
# a document's own rows to each other).
_DEBIT_COLUMN_X = 700.0
_CREDIT_COLUMN_X = 850.0


def _column_baseline_graph() -> tuple[ClaimGraph, Decimal, int]:
    """Opening 1000, then 3 genuine credit rows (at the credit column) and 3 genuine debit rows (at
    the debit column), interleaved and all correctly reconciling — enough same-document rows to let
    the geometric check establish this document's own column layout. Returns the graph, the running
    balance after these rows, and the next free transaction index for a test to append its own row."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    g.add(_money("account", "opening_balance", "1000.00"))
    running = Decimal("1000.00")
    seq = 0
    for kind, amount, x in (
        ("credit", "500.00", _CREDIT_COLUMN_X),
        ("debit", "100.00", _DEBIT_COLUMN_X),
        ("credit", "200.00", _CREDIT_COLUMN_X),
        ("debit", "50.00", _DEBIT_COLUMN_X),
        ("credit", "300.00", _CREDIT_COLUMN_X),
        ("debit", "75.00", _DEBIT_COLUMN_X),
    ):
        running = running + Decimal(amount) if kind == "credit" else running - Decimal(amount)
        g.add(_money_at(f"transaction_{seq}", kind, amount, index=seq, bbox=(x, seq * 30.0, 50.0, 20.0)))
        g.add(_money_at(
            f"transaction_{seq}", "running_balance", str(running),
            index=seq, bbox=(950.0, seq * 30.0, 50.0, 20.0),
        ))
        seq += 1
    return g, running, seq


# =================================================================================================
# check_kinds (pure)
# =================================================================================================


def test_linear_balance_passes_and_localizes():
    ok = checks.linear_balance(
        Decimal("1000"),
        [(0, Decimal("500"), None, Decimal("1500")), (1, None, Decimal("200"), Decimal("1300"))],
        TOL,
    )
    assert ok.passed
    bad = checks.linear_balance(
        Decimal("1000"),
        [(0, Decimal("500"), None, Decimal("1500")), (1, None, Decimal("200"), Decimal("1350"))],
        TOL,
    )
    assert not bad.passed and bad.breaks[0].index == 1 and bad.breaks[0].expected == Decimal("1300")


def test_linear_balance_insufficient_without_anchor_or_balances():
    assert not checks.linear_balance(None, [(0, Decimal("1"), None, Decimal("1"))], TOL).evaluated
    one = checks.linear_balance(Decimal("1000"), [(0, Decimal("500"), None, Decimal("1500"))], TOL)
    assert not one.evaluated  # <2 printed balances


def test_linear_balance_reanchors_so_one_edit_does_not_cascade():
    """Re-anchoring confines ONE genuine edit to its row + the next; later genuine rows stay clean.

    Open 1000; +500→1500, +100→(genuine 1600, TAMPERED to 9999), +100→1700, +100→1800. Without
    re-anchoring every downstream row would break; with it, only rows 1 and 2 break and row 3 (1700→
    1800, genuine) is clean — proving a single edit is localized, not cascaded into a false storm.
    """
    rows = [
        (0, Decimal("500"), None, Decimal("1500")),
        (1, Decimal("100"), None, Decimal("9999")),  # tampered (genuine would be 1600)
        (2, Decimal("100"), None, Decimal("1700")),  # genuine value, no longer follows the tamper
        (3, Decimal("100"), None, Decimal("1800")),  # genuine, follows row 2 → must stay clean
    ]
    out = checks.linear_balance(Decimal("1000"), rows, TOL)
    assert [b.index for b in out.breaks] == [1, 2]  # localized to the edit + dependent, NOT row 3


def test_equation_and_comparison_and_sum_and_monotonic():
    assert checks.equation([(1, Decimal("50000")), (-1, Decimal("8000"))], Decimal("42000"), TOL).passed
    assert not checks.equation([(1, Decimal("50000")), (-1, Decimal("8000"))], Decimal("45000"), TOL).passed
    assert not checks.equation([(1, None)], Decimal("1"), TOL).evaluated
    assert checks.comparison(Decimal("5"), "<=", Decimal("9")).passed
    assert not checks.comparison(Decimal("9"), "<=", Decimal("5")).passed
    assert checks.sum_equals([Decimal("100"), Decimal("100")], Decimal("200"), TOL).passed
    assert not checks.sum_equals([Decimal("100")], Decimal("999"), TOL).passed
    assert checks.sequence_monotonic([(0, 1), (1, 2), (2, 2)], strict=False).passed
    assert not checks.sequence_monotonic([(0, 2), (1, 1)], strict=False).passed


# =================================================================================================
# the financial pack — discrimination + must-fail
# =================================================================================================


def test_genuine_statement_passes_every_invariant():
    assert _status_map(_statement(dates=("01/01/2024", "15/01/2024"))) == {
        "F1": "PASS",
        "F2": "PASS",
        "F3": "PASS",
        "F4": "PASS",
        "F5": "PASS",
    }


def test_single_edited_balance_breaks_chain_and_localizes_the_cell():
    """MUST-FAIL FIXTURE: one altered running balance breaks F1 at the exact row, with its bbox."""
    f1 = _rule(_statement(row1_balance="1350.00"), "F1")
    assert f1.status == RuleStatus.FAIL
    assert f1.suspicion == pytest.approx(0.90)  # hard_tamper severity from _shared.json
    assert f1.evidence[0].index == 1 and f1.evidence[0].bbox == (1, 2, 3, 4)
    assert f1.evidence[0].expected == "1300.00" and f1.evidence[0].printed == "1350.00"


def _gap_statement():
    """4-row statement with an UNGROUNDED row (row 1) between two confirmed rows, plus a genuine
    tamper at row 3. Mirrors the real failure mode: a page whose credit/debit AND balance all failed
    the cross-read (agree=False) — not because anything was edited, but because the reader never
    grounded that page. Open 1000; row0 +500→1500 (confirmed); row1 +200→(ungrounded, real value would
    be 1700); row2 −100→1600 (confirmed, but wrongly appears to mismatch since row1's real +200 was
    dropped from ``expected``); row3 −300→999 (TAMPERED, genuine value would be 1300, confirmed).
    """
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    g.add(_money("account", "opening_balance", "1000.00"))
    g.add(_money("transaction_0", "credit", "500.00", index=0))
    g.add(_money("transaction_0", "running_balance", "1500.00", index=0))
    g.add(_money("transaction_1", "credit", "200.00", index=1, agree=False))  # ungrounded page
    g.add(_money("transaction_1", "running_balance", "1700.00", index=1, agree=False))  # ungrounded
    g.add(_money("transaction_2", "debit", "100.00", index=2))
    g.add(_money("transaction_2", "running_balance", "1600.00", index=2))  # confirmed, genuine
    g.add(_money("transaction_3", "debit", "300.00", index=3))
    g.add(_money("transaction_3", "running_balance", "999.00", index=3))  # confirmed, TAMPERED (genuine 1300)
    return g


def test_gap_from_ungrounded_page_is_not_evaluated_never_a_false_fail():
    """The fix: a mismatch whose only cause is an unconfirmed (ungrounded) run of rows must NOT be
    reported as tamper evidence — it proves a grounding gap, not an edited figure (CLAUDE.md §3.3)."""
    f1 = _rule(_gap_statement(), "F1")
    assert f1.status == RuleStatus.FAIL  # the doc has ONE genuine tamper (row 3) — see next test
    assert [e.index for e in f1.evidence] == [3]  # row 2's gap-caused mismatch is EXCLUDED
    assert f1.evidence[0].expected == "1300.00" and f1.evidence[0].printed == "999.00"


def test_gap_alone_without_a_genuine_edit_is_not_evaluated():
    """Isolate the gap: drop the row-3 tamper so the ONLY mismatch is the gap-caused one at row 2 —
    F1 must come back NOT_EVALUATED, never FAIL, on a genuinely untampered statement."""
    g = _gap_statement()
    row3_balance = next(
        c for c in g.claims if c.subject == "transaction_3" and c.predicate == "running_balance"
    )
    row3_balance.value = "1300.00"  # restore the genuine (untampered) figure
    f1 = _rule(g, "F1")
    assert f1.status == RuleStatus.NOT_EVALUATED
    assert "could not be independently confirmed" in f1.reason


def test_column_mislabeled_row_is_not_evaluated_never_a_false_fail():
    """MUST-FAIL FIXTURE: observed in production — a genuine credit (savings interest) was read into
    the debit slot. The number and its box are both confirmed (real, grounded) — only the COLUMN LABEL
    is wrong. A row whose own bbox sits in the OTHER column's geometric position (established purely
    from this document's own 6 baseline rows, no hardcoded column position) must not be reported as
    confirmed tamper. Would FAIL (F1 would FAIL as if this were an edited figure) against the pre-fix
    code, which had no geometric column check at all."""
    g, running, seq = _column_baseline_graph()
    # A genuine credit of 20.00 — but the reader labelled it "debit" AND put its box at the CREDIT
    # column's x-position (consistent with it truly being a credit, just mislabeled).
    genuine_balance = running + Decimal("20.00")
    g.add(_money_at(
        f"transaction_{seq}", "debit", "20.00", index=seq, bbox=(_CREDIT_COLUMN_X, seq * 30.0, 50.0, 20.0)
    ))
    g.add(_money_at(
        f"transaction_{seq}", "running_balance", str(genuine_balance),
        index=seq, bbox=(950.0, seq * 30.0, 50.0, 20.0),
    ))
    f1 = _rule(g, "F1")
    assert f1.status == RuleStatus.NOT_EVALUATED
    assert "mislabeled" in f1.reason or "geometrically inconsistent" in f1.reason


def test_genuine_edit_in_a_correctly_labeled_column_still_fails():
    """Crown-jewel regression: the SAME baseline layout, but this time the tampered row's box sits in
    its OWN (correctly-labelled) column — a real edited figure, not a column mislabel — must still FAIL
    confidently. Proves the geometric check only suppresses genuinely ambiguous rows, never a real one."""
    g, running, seq = _column_baseline_graph()
    # A genuine debit of 20.00, correctly labelled AND correctly positioned in the debit column — but
    # the printed running balance is fabricated (a real edit): should be running-20, but claims +20.
    fabricated_balance = running + Decimal("20.00")
    g.add(_money_at(
        f"transaction_{seq}", "debit", "20.00", index=seq, bbox=(_DEBIT_COLUMN_X, seq * 30.0, 50.0, 20.0)
    ))
    g.add(_money_at(
        f"transaction_{seq}", "running_balance", str(fabricated_balance),
        index=seq, bbox=(950.0, seq * 30.0, 50.0, 20.0),
    ))
    f1 = _rule(g, "F1")
    assert f1.status == RuleStatus.FAIL
    assert f1.evidence[0].index == seq


def _real_world_style_graph() -> ClaimGraph:
    """Mirrors a real production incident (mom_bank_statement.pdf) byte-for-byte: a genuine Canara
    statement whose page-1 read from gemini-2.5-flash put two genuine CREDIT rows' amounts into the
    DEBIT slot AND returned no bbox at all for those two cells (it grounded the other two rows on the
    same page with real boxes) — too few bbox-having same-predicate rows anywhere in the document for
    `_column_mislabeled_rows` to build a geometric baseline (it abstains). Open 1485.34; -164.58->
    1320.76 (real debit, confirmed, grounded); +58.00->1378.76 (real CREDIT, mislabeled debit, no bbox);
    -58.00->1320.76 (real debit, confirmed, grounded); +200.00->1520.76 (real CREDIT, mislabeled debit,
    no bbox). Pre-fix, this reported a confident 90%-suspicion FAIL on a completely genuine statement."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    g.add(_money("account", "opening_balance", "1485.34"))
    g.add(_money_at("transaction_0", "debit", "164.58", index=0, bbox=(700.0, 0.0, 50.0, 20.0)))
    g.add(_money_at("transaction_0", "running_balance", "1320.76", index=0, bbox=(950.0, 0.0, 50.0, 20.0)))
    g.add(_money_at("transaction_1", "debit", "58.00", index=1, bbox=None))
    g.add(_money_at("transaction_1", "running_balance", "1378.76", index=1, bbox=(950.0, 30.0, 50.0, 20.0)))
    g.add(_money_at("transaction_2", "debit", "58.00", index=2, bbox=(700.0, 60.0, 50.0, 20.0)))
    g.add(_money_at("transaction_2", "running_balance", "1320.76", index=2, bbox=(950.0, 60.0, 50.0, 20.0)))
    g.add(_money_at("transaction_3", "debit", "200.00", index=3, bbox=None))
    g.add(_money_at("transaction_3", "running_balance", "1520.76", index=3, bbox=(950.0, 90.0, 50.0, 20.0)))
    return g


def test_bbox_free_column_swap_is_not_evaluated_never_a_false_reject():
    """MUST-FAIL FIXTURE (production regression): with no bbox to measure, the geometric check
    abstains — pre-fix, both mislabeled rows fell through as confirmed tamper. The bbox-free swap check
    must catch them from the arithmetic alone (`_bbox_free_swap_rows`), turning a false REJECT into an
    honest NOT_EVALUATED."""
    f1 = _rule(_real_world_style_graph(), "F1")
    assert f1.status == RuleStatus.NOT_EVALUATED
    assert "swapped" in f1.reason


def test_bbox_free_tamper_without_a_plausible_swap_still_fails():
    """Guard against over-suppression: the bbox-free swap check must only excuse a break that ACTUALLY
    reconciles under the swap hypothesis, never every ungrounded break. A real edit with no bbox and no
    swap match must still FAIL, localized to its own row."""
    g = _real_world_style_graph()
    row3_balance = next(
        c for c in g.claims if c.subject == "transaction_3" and c.predicate == "running_balance"
    )
    # Genuine forward value is 1520.76; the debit-labelled swap-reconciled value would be 1120.76 (per
    # the fixture above) — 1999.99 matches neither, so this is an unexplained edit, not a mislabel.
    row3_balance.value = "1999.99"
    f1 = _rule(g, "F1")
    assert f1.status == RuleStatus.FAIL
    assert f1.evidence[0].index == 3


def test_uncounted_movement_holds_net_reconciliation_and_column_totals_pending():
    """F3/F4 must not silently exclude an unconfirmed transaction amount from a sum — doing so changes
    the sum's meaning (real movement goes missing), producing a confident but false mismatch."""
    g = _gap_statement()
    g.add(_money("account", "closing_balance", "1300.00"))
    g.add(_money("summary", "total_debits", "400.00"))
    g.add(_money("summary", "total_credits", "700.00"))
    statuses = _status_map(g)
    assert statuses["F3"] == "NOT_EVALUATED"
    assert statuses["F4"] == "NOT_EVALUATED"
    f4 = _rule(g, "F4")
    assert "could not be independently confirmed" in f4.reason


def test_edited_total_breaks_only_column_totals():
    statuses = _status_map(_statement(total_debits="999.00"))
    assert statuses["F3"] == "FAIL"
    assert statuses["F1"] == "PASS"  # the chain is untouched — discrimination, not a blanket fail


def test_edited_closing_breaks_reconciliation():
    statuses = _status_map(_statement(closing="9999.00"))
    assert statuses["F2"] == "FAIL" and statuses["F4"] == "FAIL"


def test_laundered_figure_is_not_evaluated_never_scored():
    """The §5.2→§4 handoff: a cross-read-FAILED balance is missing, not a tamper and not a pass."""
    statuses = _status_map(_statement(row1_balance="1350.00", agree=False))
    assert statuses["F1"] == "NOT_EVALUATED"  # the untrusted figure cannot be chained
    assert statuses["F2"] == "NOT_EVALUATED"  # the last balance is untrusted → cannot assert
    # a FAIL is never manufactured from an untrusted number
    assert all(s != "FAIL" for k, s in statuses.items() if k in {"F1", "F2"})


def test_low_confidence_figure_is_not_evaluated():
    g = _statement()
    # drop the opening balance's confidence below the gate → F1/F4 can't anchor
    g.claims[0] = _money("account", "opening_balance", "1000.00", conf=0.2)
    statuses = _status_map(g)
    assert statuses["F1"] == "NOT_EVALUATED" and statuses["F4"] == "NOT_EVALUATED"


def test_backdated_row_breaks_date_monotonicity():
    assert _status_map(_statement(dates=("15/01/2024", "01/01/2024")))["F5"] == "FAIL"


def test_salary_slip_identity():
    def slip(net):
        g = ClaimGraph(doc_id="d", doc_type="SALARY_SLIP")
        g.add(_money("salary_slip", "gross_earnings", "50000"))
        g.add(_money("salary_slip", "total_deductions", "8000"))
        g.add(_money("salary_slip", "net_pay", net))
        return g

    assert _rule(slip("42000"), "F6").status == RuleStatus.PASS
    assert _rule(slip("45000"), "F6").status == RuleStatus.FAIL


def test_income_proof_consistency():
    def income(taxable):
        g = ClaimGraph(doc_id="d", doc_type="FORM16")
        g.add(_money("income_proof", "gross_income", "900000"))
        g.add(_money("income_proof", "taxable_income", taxable))
        return g

    assert _rule(income("750000"), "F7").status == RuleStatus.PASS
    assert _rule(income("950000"), "F7").status == RuleStatus.FAIL  # taxable > gross


# =================================================================================================
# engine + analyzer
# =================================================================================================


def test_engine_selects_pack_by_doc_type():
    assert engine.domain_for_doc_type("BANK_STATEMENT") == "financial"
    assert engine.domain_for_doc_type("SALARY_SLIP") == "financial"
    assert engine.domain_for_doc_type("LAND_DEED") is None
    domain, results = engine.run(
        ClaimGraph(doc_id="d", doc_type="PASSPORT"), min_confidence=GATE, tolerance=1.0
    )
    assert domain is None and results == []


def _ctx_with(graph) -> AnalysisContext:
    ctx = AnalysisContext(session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF")
    if graph is not None:
        ctx.shared["claim_graph"] = graph
    return ctx


def test_analyzer_not_evaluated_without_graph():
    sig = ConsistencyRulesAnalyzer().analyze(_ctx_with(None))
    assert sig.status == SignalStatus.NOT_EVALUATED and sig.suspicion is None


def test_analyzer_clean_on_genuine_and_flags_tampered():
    az = ConsistencyRulesAnalyzer()
    clean = az.analyze(_ctx_with(_statement(dates=("01/01/2024", "15/01/2024"))))
    tampered = az.analyze(_ctx_with(_statement(row1_balance="1350.00")))
    assert clean.status == SignalStatus.VALID and clean.suspicion == 0.0
    assert tampered.status == SignalStatus.VALID and tampered.suspicion >= 0.85
    assert tampered.suspicion > clean.suspicion  # the discriminating property
    assert tampered.evidence_regions, "a caught edit must localize a cell for the underwriter"
    assert tampered.measurements["rules_failed"] >= 1


def test_aggregate_only_discrepancy_is_review_not_reject_on_claim_graph():
    """KNOWN_ISSUES #4: rows chain, only a stated total is off -> REVIEW band, never an auto-reject.

    total_debits is stated 250 but the single debit is 200; every running balance still carries forward
    (F1 passes), so only the aggregate column-total (F3) breaks. That is indistinguishable from an
    unextracted fee, so it must land in the REVIEW band — not the 0.9 the old code produced. Would FAIL
    against the old analyzer (which took the rulebook's hard_tamper severity for any fail).
    """
    sig = ConsistencyRulesAnalyzer().analyze(_ctx_with(_statement(total_debits="250.00")))
    assert sig.status == SignalStatus.VALID
    assert sig.measurements["rules_failed"] >= 1
    assert sig.measurements["severity"] == "aggregate_only"
    # score = 100*(1-susp) >= 60 -> REVIEW, never REJECT, on a lone aggregate discrepancy.
    assert sig.suspicion is not None and sig.suspicion <= 0.40


def test_running_balance_edit_stays_strong_on_claim_graph():
    """Discrimination guard: an edited transaction balance breaks the chain -> full tamper strength."""
    sig = ConsistencyRulesAnalyzer().analyze(_ctx_with(_statement(row1_balance="1350.00")))
    assert sig.suspicion is not None and sig.suspicion >= 0.85
    assert sig.measurements["severity"] == "running_balance_break"


def test_incomplete_extraction_abstains_on_claim_graph():
    """A break coinciding with OCR-flagged uncaptured money must ABSTAIN, not assert tampering.

    Same broken ledger, two completeness states: with the OCR path reporting an uncaptured monetary
    figure the analyzer is pending (REVIEW); without it, the identical break is a confident tamper.
    Proves the cross-path completeness signal actually gates the verdict (KNOWN_ISSUES #4).
    """
    from forensics.arithmetic import StatementData

    az = ConsistencyRulesAnalyzer()
    ctx = _ctx_with(_statement(row1_balance="1350.00"))          # a running-balance break
    ctx.shared["statement"] = StatementData(unstructured_money_tokens=1)  # OCR saw uncaptured money
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED and sig.suspicion is None

    # Without the incompleteness signal, the SAME break is a confident tamper -> the gate really acts.
    sig2 = az.analyze(_ctx_with(_statement(row1_balance="1350.00")))
    assert sig2.status == SignalStatus.VALID and sig2.suspicion is not None and sig2.suspicion >= 0.85


def test_analyzer_not_evaluated_when_nothing_assertable():
    """Every critical figure failed the cross-read → no invariant assertable → honest pending."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    g.add(_money("account", "opening_balance", "1000.00", agree=False))
    g.add(_money("transaction_0", "running_balance", "1500.00", index=0, agree=False))
    g.add(_money("transaction_1", "running_balance", "1300.00", index=1, agree=False))
    sig = ConsistencyRulesAnalyzer().analyze(_ctx_with(g))
    assert sig.status == SignalStatus.NOT_EVALUATED and sig.suspicion is None


def test_analyzer_not_evaluated_for_unhandled_doc_type():
    sig = ConsistencyRulesAnalyzer().analyze(_ctx_with(ClaimGraph(doc_id="d", doc_type="PASSPORT")))
    assert sig.status == SignalStatus.NOT_EVALUATED
