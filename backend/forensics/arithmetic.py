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
    # One-pass financial-summary terms (KNOWN_ISSUES #4). Fees/charges/GST/taxes and interest are often
    # stated in a summary block and affect the closing balance WITHOUT appearing as a transaction row.
    # Feeding them to the net-reconciliation invariant lets a genuine statement with such adjustments
    # reconcile cleanly instead of tripping a false aggregate break. ``None`` = none stated (unchanged
    # behaviour). They never enter the per-row running chain, so they cannot mask an edited-figure tamper.
    stated_charges: Decimal | None = None   # money OUT not itemised as a debit (fees/charges/GST/tax)
    stated_interest: Decimal | None = None  # money IN not itemised as a credit (interest credited)
    # Multi-page zipper (KNOWN_ISSUES #4): each (page_closing, next_page_opening) boundary pair, in
    # page order. A genuine multi-page statement carries the closing of page n forward as the opening of
    # page n+1; a deleted page to hide transactions breaks the continuity. Empty ⇒ single page / not checked.
    page_boundaries: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    # Completeness signal (CLAUDE.md §3.1/§4): count of currency-formatted figures the parser saw on
    # the page but could NOT place into the transaction table (e.g. a fee/charge/interest line in a
    # layout region the header columns don't cover). > 0 means the extracted ledger is incomplete, so a
    # downstream arithmetic imbalance may be an EXTRACTION gap, not tampering — the engine abstains
    # rather than false-reject a genuine statement. Defaults to 0 (complete) so existing callers/tests
    # that build a StatementData directly keep asserting tampering exactly as before.
    unstructured_money_tokens: int = 0


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
    scale: Decimal = Decimal(0)  # the statement's monetary scale (median balance); grades materiality


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

    # --- Invariant 2: closing balance = last running balance (± summary charges/interest) ---------
    # A summary fee/interest stated after the last transaction row moves the closing below/above the last
    # printed running balance, so fold those one-pass terms in here too (KNOWN_ISSUES #4) — else a genuine
    # statement with a stated charge trips a false closing-balance break.
    last_printed = next((t.balance for t in reversed(txns) if t.balance is not None), None)
    if stmt.closing_balance is not None and last_printed is not None:
        if _off_scale(stmt.closing_balance, scale) or _off_scale(last_printed, scale):
            unreadable += 1
        else:
            checks += 1
            charges = stmt.stated_charges or Decimal(0)
            interest = stmt.stated_interest or Decimal(0)
            expected_closing = last_printed - charges + interest
            if not _close(stmt.closing_balance, expected_closing):
                violations.append(
                    Violation("closing_balance", None, expected_closing, stmt.closing_balance)
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

    # --- Invariant 4: net reconciliation (opening + credits + interest - debits - charges == closing).
    # Stated fees/charges/taxes and interest (KNOWN_ISSUES #4) affect the closing balance without being
    # itemised as transaction rows; folding the one-pass financial-summary terms in here lets a genuine
    # statement with such adjustments reconcile cleanly instead of tripping a false aggregate break. They
    # never touch the per-row running chain (invariant 1), so they cannot mask an edited-figure tamper.
    if stmt.closing_balance is not None:
        if _off_scale(stmt.closing_balance, scale):
            unreadable += 1
        else:
            checks += 1
            charges = stmt.stated_charges or Decimal(0)
            interest = stmt.stated_interest or Decimal(0)
            expected_close = stmt.opening_balance + sum_credit + interest - sum_debit - charges
            if not _close(expected_close, stmt.closing_balance):
                violations.append(
                    Violation("net_reconciliation", None, expected_close, stmt.closing_balance)
                )

    # --- Invariant 5: multi-page zipper (page n closing carries forward to page n+1 opening) ---------
    # A genuine multi-page statement prints the closing balance of one page as the opening/brought-forward
    # of the next. A deleted page (to hide transactions) breaks the continuity. A boundary figure that is
    # an off-scale misparse is dropped, not asserted (same discipline as the balance chain).
    for i, (page_close, next_open) in enumerate(stmt.page_boundaries):
        if _off_scale(page_close, scale) or _off_scale(next_open, scale):
            unreadable += 1
            continue
        checks += 1
        if not _close(page_close, next_open):
            violations.append(Violation("page_zipper", i, page_close, next_open))

    # Decision (CLAUDE.md §3.1/§4): plausible breaks → flag as tamper. No breaks but some figures were
    # unreadable misparses → NOT_EVALUATED (couldn't reliably read it → pending/REVIEW, never a
    # confident "tampered" off garbage). Otherwise everything reconciled → clean.

    # Completeness abstain: if the page carried monetary figures we could NOT place into the table, the
    # extracted ledger is incomplete. An imbalance may then be OUR gap (an unextracted fee/charge/
    # interest line), not the applicant's fraud — so we must not assert tampering off an incomplete
    # ledger. Abstain to REVIEW. A complete-but-inconsistent ledger still flags below. (This is the
    # honest fix for genuine statements with hidden charges being false-rejected — CLAUDE.md §3.1/§4.)
    if violations and stmt.unstructured_money_tokens > 0:
        return ConsistencyResult(
            evaluated=False,
            checks_run=checks,
            scale=scale,
            reason=(
                f"{stmt.unstructured_money_tokens} monetary figure(s) on the page were not captured in "
                "the transaction table — extraction is incomplete, so the imbalance cannot be "
                "attributed to tampering; left pending (REVIEW), not asserted as tampered"
            ),
        )

    if not violations and unreadable:
        return ConsistencyResult(
            evaluated=False,
            checks_run=checks,
            scale=scale,
            reason=(
                f"{unreadable} balance figure(s) implausible against the statement's ~{scale} scale — "
                "likely OCR/text-layer misparse(s); left pending, not asserted as tampered"
            ),
        )

    return ConsistencyResult(
        evaluated=True,
        violations=violations,
        checks_run=checks,
        scale=scale,
        reason=f"{checks} invariant(s) checked, {len(violations)} violated",
    )


# --- Failure-typing tunables. DEFAULT — needs calibration on a real corpus (CLAUDE.md §5). --------
# A benign extraction gap (an unextracted fee/charge/interest reflected in the balances but not
# itemised) moves the AGGREGATE by a small amount relative to the statement's scale; a figure edited to
# deceive an underwriter moves it by a MATERIAL amount. Used ONLY to grade an aggregate-only
# discrepancy (one where the per-row running chain is fully intact).
ARITH_MATERIAL_DELTA_FRAC = 0.10
# Aggregate-only (no running-balance break) suspicion bands. BOTH sit in/at the REVIEW band so a lone
# aggregate discrepancy NEVER, by itself, auto-REJECTS a document (score = 100*(1-susp): 0.30→70,
# 0.40→60, both ≥ review_at=60). It routes to a human with the exact expected-vs-printed evidence,
# and combines with other signals to tip a verdict — but a genuine statement with an unextracted fee is
# never false-rejected on this alone. A running-balance break, by contrast, stays full tamper strength.
SUSPICION_AGGREGATE_MINOR = 0.30     # immaterial residual — most likely an unextracted fee/charge
SUSPICION_AGGREGATE_MATERIAL = 0.40  # material stated-total/closing contradiction — flag for review


def _suspicion_from(result: ConsistencyResult) -> float:
    """Map violations to suspicion, typed by WHICH invariant broke (CLAUDE.md §3.1/§4).

    A broken RUNNING-BALANCE chain is the hard signature of an edited transaction figure — a printed
    balance that does not follow from its neighbours — so it is strong tamper evidence. An
    AGGREGATE-ONLY discrepancy (every balance chains, but a stated total / closing / net-reconciliation
    is off) is ambiguous: an unextracted aggregate fee/charge produces it just as an edited stated-total
    does. We cannot separate them from the numbers, so it is graded into the REVIEW band, never an
    auto-REJECT — the difference that stops genuine statements with hidden charges being false-rejected.
    """
    if not result.violations:
        return 0.0
    kinds = {v.kind for v in result.violations}
    # A running-balance break (edited transaction figure) or a page-zipper break (a page boundary that
    # doesn't carry forward — a deleted/inserted page) is a chain discontinuity: strong tamper evidence.
    if "running_balance" in kinds or "page_zipper" in kinds:
        # More independent breaks -> more suspicious, asymptotically. Tamper strength.
        return min(1.0, 0.9 + 0.05 * (len(result.violations) - 1))
    # Aggregate-only: grade by materiality of the largest residual against the statement's scale.
    max_delta = max((v.delta for v in result.violations), default=Decimal(0))
    material = result.scale > 0 and max_delta >= result.scale * Decimal(str(ARITH_MATERIAL_DELTA_FRAC))
    return SUSPICION_AGGREGATE_MATERIAL if material else SUSPICION_AGGREGATE_MINOR


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
        # Failure severity, surfaced for the console (§9): a running-balance break is an edited-figure
        # signature (tamper); an aggregate-only break is ambiguous with an unextracted fee (→ review).
        kinds = {v.kind for v in result.violations}
        if not result.violations:
            severity = "clean"
        elif "running_balance" in kinds or "page_zipper" in kinds:
            severity = "running_balance_break"
        else:
            severity = "aggregate_only"
        measurements: dict[str, Any] = {
            "checks_run": result.checks_run,
            "severity": severity,
            "violations": [
                {"kind": v.kind, "index": v.index, "expected": str(v.expected),
                 "printed": str(v.printed), "delta": str(v.delta)}
                for v in result.violations
            ],
            "honest_bound": HONEST_BOUND,
        }
        if not result.violations:
            reason = "all arithmetic invariants reconcile"
        elif severity == "running_balance_break":
            reason = (
                f"{len(result.violations)} invariant(s) broken including the running-balance chain — "
                "an edited transaction figure"
            )
        else:
            reason = (
                f"{len(result.violations)} aggregate invariant(s) off but every printed balance chains — "
                "an unextracted fee/charge or an edited stated total; routed to review, not asserted "
                "as tampering"
            )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_arithmetic_consistency, reason,
            evidence_regions=regions, measurements=measurements,
        )
