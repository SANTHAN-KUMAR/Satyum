"""Tier-2 PRIMARY signal: cross-field / arithmetic consistency for financial statements.

The innovation thesis (ADR-003): a forger — human or GenAI — can produce pixel-perfect output but
cannot keep the document's *internal arithmetic* coherent. We recompute every invariant a genuine
bank statement must satisfy and flag exactly what broke:

  * running balance:  balance[i] == balance[i-1] + credit[i] - debit[i]   (chained from opening)
  * closing balance:  last running balance == printed/stated closing balance
  * column totals:     sum(debits) == stated total debits;  sum(credits) == stated total credits
  * net reconciliation: opening + total_credits - total_debits == closing

Edit one printed figure and at least one invariant breaks at a locatable row — strong tamper
evidence that survives the capture medium because it operates on *read numbers*, not pixels.

Honest bound (ADR-003): this catches single-field edits and incoherent GenAI output, NOT a fully
recomputed-and-reprinted forgery (every total made consistent) — that residual is covered by
provenance + resubmission memory + the cross-document graph. The reason string says so.

Pure Python (``Decimal``) — no heavy deps; directly unit-tested with genuine vs single-edit pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import settings
from app.contracts import (
    AnalysisContext,
    EvidenceRegion,
    LayerSignal,
    Mode,
)

BBox = tuple[float, float, float, float]


@dataclass
class Transaction:
    index: int
    debit: Decimal | None = None
    credit: Decimal | None = None
    balance: Decimal | None = None
    date: str | None = None
    description: str | None = None
    balance_bbox: BBox | None = None


@dataclass
class StatementData:
    """Structured statement, as produced upstream by OCR/parse (ctx.shared['statement'])."""

    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    transactions: list[Transaction] = field(default_factory=list)
    stated_total_debits: Decimal | None = None
    stated_total_credits: Decimal | None = None


@dataclass
class Violation:
    kind: str
    index: int | None
    expected: Decimal
    printed: Decimal
    bbox: BBox | None = None

    @property
    def delta(self) -> Decimal:
        return (self.printed - self.expected).copy_abs()


@dataclass
class ConsistencyResult:
    evaluated: bool
    violations: list[Violation] = field(default_factory=list)
    checks_run: int = 0
    reason: str = ""


def _tol() -> Decimal:
    return Decimal(str(settings.arithmetic_abs_tolerance))


def _close(a: Decimal, b: Decimal) -> bool:
    return (a - b).copy_abs() <= _tol()


def _statement_scale(stmt: StatementData) -> Decimal:
    """The statement's typical monetary magnitude — the MEDIAN absolute balance (robust to one garbage
    cell). Used to tell a misparsed figure (far below scale) from a plausible edited one (at scale)."""
    mags = sorted(
        abs(b)
        for b in [stmt.opening_balance, stmt.closing_balance, *(t.balance for t in stmt.transactions)]
        if b is not None and b != 0
    )
    if not mags:
        return Decimal(0)
    mid = len(mags) // 2
    return mags[mid] if len(mags) % 2 == 1 else (mags[mid - 1] + mags[mid]) / 2


def _off_scale(printed: Decimal, scale: Decimal) -> bool:
    """True when a printed balance is implausibly small versus the statement's scale — the signature of
    a truncated/garbage parse (e.g. '1' amid ₹2-lakh balances), not a plausible edited figure. A real
    single-field edit substitutes a figure of *similar* magnitude, so it stays above the threshold."""
    return scale > 0 and printed.copy_abs() < scale * Decimal(str(settings.arithmetic_misparse_ratio))


def check_consistency(stmt: StatementData) -> ConsistencyResult:
    """Recompute every invariant. Pure function — no I/O, fully deterministic."""
    violations: list[Violation] = []
    checks = 0

    txns = stmt.transactions
    have_balances = sum(1 for t in txns if t.balance is not None)
    have_movements = sum(1 for t in txns if t.debit is not None or t.credit is not None)

    # Not enough structure to assert anything -> honestly NOT evaluated (never a false "tampered").
    if stmt.opening_balance is None or have_balances < 2 or have_movements < 1:
        return ConsistencyResult(
            evaluated=False,
            reason="insufficient parsed structure (need opening balance + >=2 balances + movements)",
        )

    # The statement's monetary scale (median balance) — lets us tell a misparsed cell (far below scale)
    # from a plausible edited figure (at scale). Computed once; robust to a single garbage cell.
    scale = _statement_scale(stmt)
    unreadable = 0  # balance cells dropped as off-scale misparses (extraction noise, not tampering)

    # --- Invariant 1: running balance chain ----------------------------------------------
    running = stmt.opening_balance
    for t in txns:
        credit = t.credit or Decimal(0)
        debit = t.debit or Decimal(0)
        expected = running + credit - debit
        if t.balance is None:
            running = expected
            continue
        if not _close(expected, t.balance):
            # A break whose printed figure is implausibly off-scale is a parse error, not a tamper:
            # drop it and do NOT cascade — re-anchor on the computed value, not the garbage cell, so a
            # single misparse can't manufacture a downstream "plausible" break (CLAUDE.md §3.1/§4).
            if _off_scale(t.balance, scale):
                unreadable += 1
                running = expected
                continue
            checks += 1
            violations.append(
                Violation("running_balance", t.index, expected, t.balance, t.balance_bbox)
            )
        else:
            checks += 1
        # Re-anchor on the PRINTED balance so a tampered figure breaks locally, not every later row.
        running = t.balance

    # --- Invariant 2: closing balance -----------------------------------------------------
    last_printed = next((t.balance for t in reversed(txns) if t.balance is not None), None)
    if stmt.closing_balance is not None and last_printed is not None:
        if _off_scale(stmt.closing_balance, scale) or _off_scale(last_printed, scale):
            unreadable += 1
        else:
            checks += 1
            if not _close(stmt.closing_balance, last_printed):
                violations.append(
                    Violation("closing_balance", None, last_printed, stmt.closing_balance)
                )

    # --- Invariant 3: column totals -------------------------------------------------------
    sum_debit = sum((t.debit for t in txns if t.debit is not None), Decimal(0))
    sum_credit = sum((t.credit for t in txns if t.credit is not None), Decimal(0))
    if stmt.stated_total_debits is not None:
        checks += 1
        if not _close(sum_debit, stmt.stated_total_debits):
            violations.append(Violation("total_debits", None, sum_debit, stmt.stated_total_debits))
    if stmt.stated_total_credits is not None:
        checks += 1
        if not _close(sum_credit, stmt.stated_total_credits):
            violations.append(Violation("total_credits", None, sum_credit, stmt.stated_total_credits))

    # --- Invariant 4: net reconciliation (opening + credits - debits == closing) ----------
    if stmt.closing_balance is not None:
        if _off_scale(stmt.closing_balance, scale):
            unreadable += 1
        else:
            checks += 1
            expected_close = stmt.opening_balance + sum_credit - sum_debit
            if not _close(expected_close, stmt.closing_balance):
                violations.append(
                    Violation("net_reconciliation", None, expected_close, stmt.closing_balance)
                )

    # Decision (CLAUDE.md §3.1/§4): plausible breaks → flag as tamper. No breaks but some figures were
    # unreadable misparses → NOT_EVALUATED (couldn't reliably read it → pending/REVIEW, never a
    # confident "tampered" off garbage). Otherwise everything reconciled → clean.
    if not violations and unreadable:
        return ConsistencyResult(
            evaluated=False,
            checks_run=checks,
            reason=(
                f"{unreadable} balance figure(s) implausible against the statement's ~{scale} scale — "
                "likely OCR/text-layer misparse(s); left pending, not asserted as tampered"
            ),
        )

    return ConsistencyResult(
        evaluated=True,
        violations=violations,
        checks_run=checks,
        reason=f"{checks} invariant(s) checked, {len(violations)} violated",
    )


def _suspicion_from(result: ConsistencyResult) -> float:
    """Map violations to suspicion. A broken running-balance chain is strong tamper evidence."""
    if not result.violations:
        return 0.0
    kinds = {v.kind for v in result.violations}
    # running_balance / net_reconciliation breaks are the hardest evidence of an edited figure
    hard = kinds & {"running_balance", "net_reconciliation", "closing_balance"}
    base = 0.9 if hard else 0.6
    # more independent violations -> more suspicious, asymptotically
    return float(min(1.0, base + 0.05 * (len(result.violations) - 1)))


HONEST_BOUND = (
    "catches single-field edits and incoherent forgeries; a fully recomputed reprint that satisfies "
    "every invariant is covered by provenance / resubmission / cross-document checks, not here"
)


class ArithmeticConsistencyAnalyzer:
    """Tier-2 analyzer wrapper. Reads the parsed statement from ``ctx.shared['statement']``."""

    name = "arithmetic_consistency"
    layer = 3
    mode = Mode.ANY  # works on a file page or a rectified camera crop alike

    def applicable(self, ctx: AnalysisContext) -> bool:
        return isinstance(ctx.shared.get("statement"), StatementData)

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        stmt = ctx.shared.get("statement")
        if not isinstance(stmt, StatementData):
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no parsed statement available"
            )
        try:
            result = check_consistency(stmt)
        except (InvalidOperation, ValueError) as exc:  # malformed numbers -> honest error, not pass
            return LayerSignal.error(self.name, self.layer, self.mode, f"parse error: {exc}")

        if not result.evaluated:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, result.reason)

        suspicion = _suspicion_from(result)
        regions = [
            EvidenceRegion(bbox=v.bbox, label=f"{v.kind}: expected {v.expected}, printed {v.printed}",
                           source=self.name)
            for v in result.violations
            if v.bbox is not None
        ]
        measurements: dict[str, Any] = {
            "checks_run": result.checks_run,
            "violations": [
                {"kind": v.kind, "index": v.index, "expected": str(v.expected),
                 "printed": str(v.printed), "delta": str(v.delta)}
                for v in result.violations
            ],
            "honest_bound": HONEST_BOUND,
        }
        reason = (
            "all arithmetic invariants reconcile" if not result.violations
            else f"{len(result.violations)} invariant(s) broken — likely edited figure(s)"
        )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_arithmetic_consistency, reason,
            evidence_regions=regions, measurements=measurements,
        )
