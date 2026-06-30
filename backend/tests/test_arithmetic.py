"""Discrimination tests for the flagship arithmetic-consistency engine.

These prove the engine *separates* genuine from tampered — and would FAIL against any constant
return (genuine must score 0 suspicion; tampered must score high — no constant satisfies both).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.arithmetic import (
    ArithmeticConsistencyAnalyzer,
    StatementData,
    Transaction,
    check_consistency,
)
from tests.builders import (
    genuine_statement,
    tampered_balance_statement,
    tampered_credit_statement,
)


def test_genuine_statement_reconciles():
    result = check_consistency(genuine_statement())
    assert result.evaluated is True
    assert result.checks_run >= 5  # 3 running balances + closing + totals + net
    assert result.violations == []


def test_single_balance_edit_is_caught_and_localised():
    result = check_consistency(tampered_balance_statement())
    assert result.evaluated is True
    assert result.violations, "an edited balance must break at least one invariant"
    kinds = {v.kind for v in result.violations}
    assert "running_balance" in kinds
    # the break must point at the tampered row (index 0) or the row that uses it as prior balance
    touched = {v.index for v in result.violations if v.index is not None}
    assert 0 in touched or 1 in touched


def test_single_credit_edit_breaks_net_reconciliation():
    # Inflating a credit but not the balances makes the column total / net reconciliation disagree.
    result = check_consistency(tampered_credit_statement())
    assert result.evaluated is True
    kinds = {v.kind for v in result.violations}
    assert kinds & {"running_balance", "net_reconciliation", "total_credits"}


def test_insufficient_structure_is_not_evaluated_not_falsely_tampered():
    sparse = StatementData(opening_balance=Decimal("100"), transactions=[
        Transaction(index=0, credit=Decimal("50")),  # no balances -> cannot assert
    ])
    result = check_consistency(sparse)
    assert result.evaluated is False
    assert result.violations == []


def test_rounding_within_tolerance_does_not_flag():
    stmt = genuine_statement()
    stmt.transactions[2].balance = Decimal("14000.50")  # 50 paise drift, within 1.0 tolerance
    stmt.closing_balance = Decimal("14000.50")
    result = check_consistency(stmt)
    assert all(v.kind != "running_balance" for v in result.violations)


# --- analyzer wrapper: the LayerSignal contract ---------------------------------------------

def _ctx_with(stmt) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["statement"] = stmt
    return ctx


def test_analyzer_discriminates_genuine_vs_tampered():
    az = ArithmeticConsistencyAnalyzer()
    genuine = az.analyze(_ctx_with(genuine_statement()))
    tampered = az.analyze(_ctx_with(tampered_balance_statement()))

    assert genuine.status == SignalStatus.VALID and genuine.suspicion == 0.0
    assert tampered.status == SignalStatus.VALID and tampered.suspicion >= 0.85
    # the discriminating property — the whole point:
    assert tampered.suspicion > genuine.suspicion
    # tampered must carry locatable evidence for the underwriter
    assert tampered.evidence_regions, "a caught edit must produce an evidence region"


def test_analyzer_not_evaluated_without_statement():
    az = ArithmeticConsistencyAnalyzer()
    sig = az.analyze(AnalysisContext(session_id="t", intake_mode=Mode.FILE))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass


@pytest.mark.parametrize("stmt_fn", [tampered_balance_statement, tampered_credit_statement])
def test_every_tampered_variant_is_flagged(stmt_fn):
    az = ArithmeticConsistencyAnalyzer()
    sig = az.analyze(_ctx_with(stmt_fn()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion > 0.5


# --- misparse / cross-read plausibility gate ------------------------------------------------------
# A genuine statement whose extraction misreads a balance cell as an off-scale figure (e.g. "1" amid
# ~₹14k balances — the real dad_canara_statement failure) must NOT be condemned as tampered. The break
# is a parse error, so the engine returns NOT_EVALUATED (pending → REVIEW), never a false REJECT — while
# a *plausible* edited figure (a real tamper) stays flagged. This is the §3.1 cross-read invariant.
import copy  # noqa: E402


def _genuine_with_balance(index: int, value: str) -> StatementData:
    stmt = copy.deepcopy(genuine_statement())
    stmt.transactions[index].balance = Decimal(value)
    return stmt


def test_offscale_misparse_last_row_is_pending_not_tampered():
    # the exact real-docs failure: the LAST balance is garbage-parsed as "1"
    result = check_consistency(_genuine_with_balance(2, "1"))
    assert result.evaluated is False, "an off-scale misparse must be pending, never a confident tamper"
    assert not result.violations
    assert "misparse" in result.reason.lower()


def test_offscale_misparse_middle_row_does_not_cascade():
    # a misparse in the MIDDLE must not manufacture a downstream 'plausible' violation
    result = check_consistency(_genuine_with_balance(1, "1"))
    assert result.evaluated is False
    assert not result.violations  # no cascade into row 2


def test_plausible_edit_still_flags_despite_the_guard():
    # a real single-field edit (15,000 -> 16,000) is at-scale, so the guard does NOT excuse it
    result = check_consistency(tampered_balance_statement())
    assert result.evaluated is True
    assert any(v.kind == "running_balance" for v in result.violations)


def test_misparse_plus_real_tamper_still_flags():
    # garbage in one cell must not hide a genuine, plausible edit elsewhere
    stmt = _genuine_with_balance(2, "1")          # misparse on the last row
    stmt.transactions[0].balance = Decimal("16000")  # real tamper on row 0
    result = check_consistency(stmt)
    assert result.evaluated is True
    assert result.violations, "a plausible edit must survive even when another cell is a misparse"


def test_analyzer_surfaces_misparse_as_not_evaluated():
    az = ArithmeticConsistencyAnalyzer()
    sig = az.analyze(_ctx_with(_genuine_with_balance(2, "1")))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass OR a false tamper
