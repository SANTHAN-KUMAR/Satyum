"""The financial rule pack (F1–F7) over the claim graph — the rehomed crown jewel (ADR-004 §4).

This is ``forensics/arithmetic.py``'s proven consistency engine, generalised off one hardcoded table
layout onto the canonical claim graph: running-balance chain, closing balance, column totals, net
reconciliation (F1–F4, production depth), plus date monotonicity (F5), salary-slip identity (F6) and
income-proof consistency (F7). Each rule reads its severity, title, and insufficiency message from the
JSON rulebook (``financial.json``) so the *policy* stays data-driven and calibrated in one place; the
*computation* dispatches to the finite ``check_kinds`` catalog.

The trust boundary is enforced here (ADR-004 §5.2): every numeric value is pulled through
:func:`_scalar`/:func:`_cell`, which return ``None`` for any cross-read-critical claim that did not
clear ``Claim.is_trusted`` — so a laundered or low-confidence figure is *missing*, never scored. A
single genuinely-edited figure (read consistently, but arithmetically wrong) breaks an invariant and
localizes the exact cell; a number the readers couldn't agree on yields NOT_EVALUATED, not a verdict.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.claims import Claim, ClaimGraph
from rules.checks import comparison, equation, linear_balance, sequence_monotonic, sum_equals
from rules.contracts import RuleEvidence, RuleResult
from rules.dates import parse_date
from rules.packbase import cell as _cell
from rules.packbase import ev as _ev
from rules.packbase import failed, not_evaluated, passed, scalar

DOMAIN = "financial"

# Document types this pack judges, and which rules apply to each (mirrors financial.json applies_when).
BANK_STATEMENT_TYPES = frozenset({"BANK_STATEMENT"})
SALARY_TYPES = frozenset({"SALARY_SLIP"})
INCOME_TYPES = frozenset({"FORM16", "ITR"})
HANDLED_DOC_TYPES = BANK_STATEMENT_TYPES | SALARY_TYPES | INCOME_TYPES

# --- claim-graph accessors (the trust gate lives in packbase) -------------------------------------
# Thin domain-local aliases over the shared pack helpers so the F1–F7 bodies read unchanged.

_scalar = scalar


def _not_evaluated(rule_id: str) -> RuleResult:
    return not_evaluated(DOMAIN, rule_id)


def _passed(rule_id: str) -> RuleResult:
    return passed(DOMAIN, rule_id)


def _failed(rule_id: str, reason: str, evidence: tuple) -> RuleResult:
    return failed(DOMAIN, rule_id, reason, evidence)


def _transactions(graph: ClaimGraph) -> list[tuple[int, dict[str, Claim]]]:
    """Statement rows assembled by sequence: ``(seq, {predicate: claim})`` in document order."""
    rows: dict[int, dict[str, Claim]] = {}
    for c in graph.claims:
        if c.subject.startswith("transaction_") and c.index is not None:
            rows.setdefault(c.index, {})[c.predicate] = c
    return [(seq, rows[seq]) for seq in sorted(rows)]


# --- the rules ------------------------------------------------------------------------------------


def f1_running_balance(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F1 — running balance carries forward; an edited figure breaks the chain at a locatable row."""
    anchor, _ = _scalar(graph, "opening_balance", gate)
    txns = _transactions(graph)
    rows: list[tuple[int, Decimal | None, Decimal | None, Decimal | None]] = []
    bal_claims: dict[int | None, Claim | None] = {}
    for seq, cells in txns:
        rows.append(
            (
                seq,
                _cell(cells.get("credit"), gate),
                _cell(cells.get("debit"), gate),
                _cell(cells.get("running_balance"), gate),
            )
        )
        bal_claims[seq] = cells.get("running_balance")

    outcome = linear_balance(anchor, rows, tol)
    if not outcome.evaluated:
        return _not_evaluated("F1")
    if outcome.passed:
        return _passed("F1")
    evidence = tuple(
        _ev("transaction", "running_balance", bal_claims.get(b.index), b) for b in outcome.breaks
    )
    first = outcome.breaks[0]
    reason = (
        f"running balance does not carry forward at row {first.index}: "
        f"expected {first.expected}, printed {first.printed}"
    )
    return _failed("F1", reason, evidence)


def f2_closing_balance(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F2 — stated closing balance equals the last running balance.

    Uses the LAST row that prints a balance — and only if that figure is trusted. If the final balance
    is missing or failed the cross-read, F2 is NOT_EVALUATED (we cannot know the true last balance),
    never a false FAIL from comparing closing to a stale earlier row.
    """
    closing, closing_claim = _scalar(graph, "closing_balance", gate)
    last_balance_claim: Claim | None = None
    for _seq, cells in reversed(_transactions(graph)):
        if "running_balance" in cells:
            last_balance_claim = cells["running_balance"]
            break
    last = _cell(last_balance_claim, gate)
    outcome = equation([(1, last)], closing, tol)
    if not outcome.evaluated:
        return _not_evaluated("F2")
    if outcome.passed:
        return _passed("F2")
    brk = outcome.breaks[0]
    reason = f"stated closing balance {brk.printed} != last running balance {brk.expected}"
    return _failed("F2", reason, (_ev("account", "closing_balance", closing_claim, brk),))


def f3_column_totals(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F3 — stated column totals equal the summed debit/credit columns."""
    txns = _transactions(graph)
    debits = [v for _, cells in txns if (v := _cell(cells.get("debit"), gate)) is not None]
    credits = [v for _, cells in txns if (v := _cell(cells.get("credit"), gate)) is not None]
    stated_debits, dr_claim = _scalar(graph, "total_debits", gate)
    stated_credits, cr_claim = _scalar(graph, "total_credits", gate)

    if stated_debits is None and stated_credits is None:
        return _not_evaluated("F3")

    evidence: list[RuleEvidence] = []
    parts: list[str] = []
    for stated, series, claim, predicate in (
        (stated_debits, debits, dr_claim, "total_debits"),
        (stated_credits, credits, cr_claim, "total_credits"),
    ):
        if stated is None:
            continue
        out = sum_equals(series, stated, tol)
        if out.evaluated and not out.passed:
            brk = out.breaks[0]
            evidence.append(_ev("summary", predicate, claim, brk))
            parts.append(f"{predicate}: summed {brk.expected} != stated {brk.printed}")
    if evidence:
        return _failed("F3", "; ".join(parts), tuple(evidence))
    return _passed("F3")


def f4_net_reconciliation(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F4 — opening + credits − debits == closing."""
    opening, _ = _scalar(graph, "opening_balance", gate)
    closing, closing_claim = _scalar(graph, "closing_balance", gate)
    if opening is None or closing is None:
        return _not_evaluated("F4")
    txns = _transactions(graph)
    sum_credit = sum(
        (v for _, cells in txns if (v := _cell(cells.get("credit"), gate)) is not None), Decimal(0)
    )
    sum_debit = sum(
        (v for _, cells in txns if (v := _cell(cells.get("debit"), gate)) is not None), Decimal(0)
    )
    outcome = equation([(1, opening), (1, sum_credit), (-1, sum_debit)], closing, tol)
    if outcome.passed:
        return _passed("F4")
    brk = outcome.breaks[0]
    reason = f"net reconciliation fails: opening + credits - debits = {brk.expected} != closing {brk.printed}"
    return _failed("F4", reason, (_ev("account", "closing_balance", closing_claim, brk),))


def f5_date_monotonicity(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F5 — transaction dates are non-decreasing (soft: legitimate same-day ordering exists)."""
    series: list[tuple[int, date | None]] = []
    claim_by_seq: dict[int | None, Claim | None] = {}
    for seq, cells in _transactions(graph):
        posted = cells.get("posted_on")
        claim_by_seq[seq] = posted
        series.append((seq, parse_date(posted.value) if (posted and posted.is_trusted(gate)) else None))
    outcome = sequence_monotonic(series, strict=False)
    if not outcome.evaluated:
        return _not_evaluated("F5")
    if outcome.passed:
        return _passed("F5")
    brk = outcome.breaks[0]
    reason = f"transaction dates not in non-decreasing order at row {brk.index}"
    return _failed("F5", reason, (_ev("transaction", "posted_on", claim_by_seq.get(brk.index), brk),))


def f6_salary_identity(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F6 — net pay == gross earnings − deductions."""
    gross, _ = _scalar(graph, "gross_earnings", gate)
    ded, _ = _scalar(graph, "total_deductions", gate)
    net, net_claim = _scalar(graph, "net_pay", gate)
    outcome = equation([(1, gross), (-1, ded)], net, tol)
    if not outcome.evaluated:
        return _not_evaluated("F6")
    if outcome.passed:
        return _passed("F6")
    brk = outcome.breaks[0]
    reason = f"net pay {brk.printed} != gross {gross} - deductions {ded}"
    return _failed("F6", reason, (_ev("salary_slip", "net_pay", net_claim, brk),))


def f7_income_consistency(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """F7 — taxable income <= gross income."""
    taxable, taxable_claim = _scalar(graph, "taxable_income", gate)
    gross, _ = _scalar(graph, "gross_income", gate)
    outcome = comparison(taxable, "<=", gross)
    if not outcome.evaluated:
        return _not_evaluated("F7")
    if outcome.passed:
        return _passed("F7")
    brk = outcome.breaks[0]
    reason = f"taxable income {taxable} exceeds gross income {gross}"
    return _failed("F7", reason, (_ev("income_proof", "taxable_income", taxable_claim, brk),))


# --- Failure-typing classification (mirrors forensics/arithmetic.py — the OCR path) ---------------
# A broken RUNNING-balance chain (F1) is the signature of an edited transaction figure — a printed
# balance that does not follow from its neighbours — so it is strong tamper evidence. An AGGREGATE-only
# break (F2/F3/F4: closing / column totals / net reconciliation, with the per-row chain intact) is
# ambiguous: an unextracted fee/charge reflected in the balances produces it just as an edited stated
# total does. We cannot separate them from the numbers, so an aggregate-only break is graded into the
# REVIEW band, never an auto-REJECT (KNOWN_ISSUES #4 — do not false-reject a genuine statement).
BALANCE_CHAIN_RULES = frozenset({"F1"})
AGGREGATE_RULES = frozenset({"F2", "F3", "F4"})
ARITHMETIC_RULES = BALANCE_CHAIN_RULES | AGGREGATE_RULES  # subject to the completeness abstain


def statement_scale(graph: ClaimGraph, gate: float) -> Decimal:
    """Median magnitude of the trusted balance figures — grades an aggregate residual's materiality.

    Robust to one garbage cell (median, not mean). Mirrors ``forensics.arithmetic._statement_scale``
    but reads the claim graph. Returns 0 when no trusted balance is present (materiality then off).
    """
    mags: list[Decimal] = []
    for pred in ("opening_balance", "closing_balance"):
        v = _scalar(graph, pred, gate)[0]
        if v is not None and v != 0:
            mags.append(abs(v))
    for _seq, cells in _transactions(graph):
        v = _cell(cells.get("running_balance"), gate)
        if v is not None and v != 0:
            mags.append(abs(v))
    if not mags:
        return Decimal(0)
    mags.sort()
    mid = len(mags) // 2
    return mags[mid] if len(mags) % 2 == 1 else (mags[mid - 1] + mags[mid]) / 2


# rule_id -> (function, applicable doc types)
_RULES: list[tuple[str, object, frozenset[str]]] = [
    ("F1", f1_running_balance, BANK_STATEMENT_TYPES),
    ("F2", f2_closing_balance, BANK_STATEMENT_TYPES),
    ("F3", f3_column_totals, BANK_STATEMENT_TYPES),
    ("F4", f4_net_reconciliation, BANK_STATEMENT_TYPES),
    ("F5", f5_date_monotonicity, BANK_STATEMENT_TYPES),
    ("F6", f6_salary_identity, SALARY_TYPES),
    ("F7", f7_income_consistency, INCOME_TYPES),
]


def evaluate(graph: ClaimGraph, *, min_confidence: float, tolerance: float) -> list[RuleResult]:
    """Run every rule applicable to the document's type; skip the rest (NOT_APPLICABLE, omitted)."""
    doc_type = (graph.doc_type or "").upper()
    tol = Decimal(str(tolerance))
    results: list[RuleResult] = []
    for _rule_id, fn, doc_types in _RULES:
        if doc_type not in doc_types:
            continue
        results.append(fn(graph, min_confidence, tol))  # type: ignore[operator]
    return results
