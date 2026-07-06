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

import statistics
from datetime import date
from decimal import Decimal

from app.claims import Claim, ClaimGraph
from rules.checks import comparison, equation, linear_balance, sequence_monotonic, sum_equals
from rules.contracts import Break, RuleEvidence, RuleResult, RuleStatus
from rules.dates import parse_date
from rules.packbase import cell as _cell
from rules.packbase import ev as _ev
from rules.packbase import failed, meta, not_evaluated, passed, scalar

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


def _not_evaluated_because(rule_id: str, reason: str) -> RuleResult:
    """NOT_EVALUATED with a reason specific to this run (e.g. naming the exact unconfirmed row/gap),
    rather than the rulebook's static insufficiency message."""
    m = meta(DOMAIN, rule_id)
    return RuleResult(rule_id, m["name"], RuleStatus.NOT_EVALUATED, None, reason)


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


def _uncounted_movement(txns: list[tuple[int, dict[str, Claim]]], gate: float) -> int:
    """How many transaction rows have a credit/debit that was extracted but failed the trust gate.

    ``_cell()`` returns ``None`` for both "this row has no such column" (a debit-only row has no
    credit) and "the claim exists but the cross-read never confirmed it" — a sum over ``_cell()``
    results cannot tell those apart, so it would silently exclude a REAL, unverifiable amount rather
    than the correct nothing. F3/F4 sum every row's movement; excluding an unconfirmed amount changes
    the sum's *meaning*, not just its precision, so a summed invariant must refuse to score across such
    a gap rather than confidently report a mismatch it cannot actually attribute to tampering (§3.3).
    """
    count = 0
    for _seq, cells in txns:
        for predicate in ("credit", "debit"):
            claim = cells.get(predicate)
            if claim is not None and not claim.is_trusted(gate):
                count += 1
    return count


# Minimum rows-per-column needed before a document's own layout can be trusted as a geometric baseline
# (fewer than this and a couple of genuinely narrow/wide cells could look like a whole misplaced column
# — insufficient evidence either way, so the check abstains rather than guess). Structural, not a
# calibrated statistic — small enough to fire on a typical multi-page statement, large enough that a
# median is not just 1-2 points.
_MIN_ROWS_PER_COLUMN_FOR_BASELINE = 3


def _bbox_x_center(bbox: tuple[float, float, float, float] | None) -> float | None:
    if bbox is None:
        return None
    x, _y, w, _h = bbox
    return x + w / 2


def _column_mislabeled_rows(txns: list[tuple[int, dict[str, Claim]]], gate: float) -> frozenset[int]:
    """Rows whose debit/credit PREDICATE looks geometrically inconsistent with the rest of THIS
    document's own table layout — a template-independent, per-document check, not a hardcoded column
    position or bank-specific rule (CLAUDE.md §6 — no invented pseudo-science, no magic numbers).

    A reader can misread which COLUMN a genuinely-printed number belongs to (observed: a savings-
    interest credit read into the debit slot) — the cross-read confirms the NUMBER at a cell, never
    which semantic column the reader assigned it to (§5.2's box-grounding covers values, not labels).
    This recovers a REAL, deterministic signal for that specific gap: every bank statement lays credit
    and debit amounts out in their own vertical band, so the median x-position of every trusted "credit"
    cell and every trusted "debit" cell — computed FRESH from this document's own rows, no other input —
    is that document's own column geometry. A row whose claimed column sits closer to the OTHER
    column's median than its own is flagged: not proof of a wrong figure, only proof the LABEL is
    questionable, so a rule using this must not treat it as confirmed tamper evidence.

    Abstains (returns empty) whenever the geometry itself is inconclusive: too few rows to trust a
    median, or the two columns' medians are not clearly separated (e.g. a layout with no distinct
    debit/credit columns at all) — never invents a column boundary that isn't really there.
    """
    xs: dict[str, list[float]] = {"debit": [], "credit": []}
    cells_by_predicate: dict[str, list[tuple[int, float]]] = {"debit": [], "credit": []}
    for seq, cells in txns:
        for predicate in ("debit", "credit"):
            claim = cells.get(predicate)
            if claim is None or not claim.is_trusted(gate):
                continue
            x = _bbox_x_center(claim.provenance.bbox if claim.provenance else None)
            if x is None:
                continue
            xs[predicate].append(x)
            cells_by_predicate[predicate].append((seq, x))

    if len(xs["debit"]) < _MIN_ROWS_PER_COLUMN_FOR_BASELINE:
        return frozenset()
    if len(xs["credit"]) < _MIN_ROWS_PER_COLUMN_FOR_BASELINE:
        return frozenset()

    debit_median = statistics.median(xs["debit"])
    credit_median = statistics.median(xs["credit"])
    column_gap = abs(credit_median - debit_median)
    # The two columns must be clearly separated relative to their own spread, else this document's
    # layout doesn't support a confident column-boundary inference (abstain rather than guess).
    spread = statistics.median(
        [abs(x - debit_median) for x in xs["debit"]] + [abs(x - credit_median) for x in xs["credit"]]
    )
    if column_gap <= max(spread * 2, 1e-6):
        return frozenset()

    outliers: set[int] = set()
    for predicate, own_median, other_median in (
        ("debit", debit_median, credit_median),
        ("credit", credit_median, debit_median),
    ):
        for seq, x in cells_by_predicate[predicate]:
            if abs(x - other_median) < abs(x - own_median):
                outliers.add(seq)
    return frozenset(outliers)


def _bbox_free_swap_rows(
    txns: list[tuple[int, dict[str, Claim]]],
    rows: list[tuple[int, Decimal | None, Decimal | None, Decimal | None]],
    breaks: tuple[Break, ...],
    tol: Decimal,
) -> frozenset[int]:
    """Confirmed breaks that reconcile exactly if THIS row's own credit and debit are swapped —
    restricted to rows whose credit/debit claim carries NO bbox at all (observed in production: a
    reader can ground page 1 with real boxes and then return a null bbox for every cell on a
    continuation page — a real reader inconsistency, not a code bug). `_column_mislabeled_rows` has no
    evidence on those rows and abstains; this closes exactly that blind spot with a self-contained
    re-check of the SAME linear-balance equation, needing no geometry at all.

    Deliberately does NOT apply when a bbox IS present. Adding exactly twice a row's own movement to a
    printed balance is arithmetically indistinguishable from a column swap — so where geometry already
    places the figure in its OWN column (positive evidence against a swap), that coincidence must be
    attributed to a real edit, never relabelled ambiguous (`test_genuine_edit_in_a_correctly_labeled_
    column_still_fails` guards this).
    """
    cells_by_index = {seq: cells for seq, cells in txns}
    by_index = {seq: (credit, debit) for seq, credit, debit, _ in rows}
    swapped: set[int] = set()
    for b in breaks:
        if b.index is None or b.expected is None or b.printed is None:
            continue
        cells = cells_by_index.get(b.index, {})
        has_bbox = any(
            claim is not None and claim.provenance is not None and claim.provenance.bbox is not None
            for claim in (cells.get("credit"), cells.get("debit"))
        )
        if has_bbox:
            continue
        credit, debit = by_index.get(b.index, (None, None))
        if credit is None and debit is None:
            continue
        swapped_expected = b.expected - 2 * ((credit or Decimal(0)) - (debit or Decimal(0)))
        if (swapped_expected - b.printed).copy_abs() <= tol:
            swapped.add(b.index)
    return frozenset(swapped)


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

    # A break right after a CONFIRMED row (unconfirmed_run == 0) is unambiguous: a printed figure that
    # matched expectations one row ago now doesn't — a genuine single-cell edit. A break preceded by a
    # run of uncompared rows (their cross-read never confirmed them — e.g. an ungrounded VLM box on an
    # entire page) only proves that stretch is unverifiable, not that any cell in it was edited;
    # reporting it as a FAIL would be exactly the fabricated certainty CLAUDE.md §3.3 forbids.
    confirmed = [b for b in outcome.breaks if b.unconfirmed_run == 0]
    weak = [b for b in outcome.breaks if b.unconfirmed_run > 0]
    if not confirmed:
        worst = max(weak, key=lambda b: b.unconfirmed_run)
        return _not_evaluated_because(
            "F1",
            f"{worst.unconfirmed_run} row(s) before row {worst.index} could not be independently "
            f"confirmed (ungrounded/unread) — the running-balance chain cannot be verified across "
            f"that gap, so a mismatch there is not attributed to tampering",
        )

    # A confirmed break can still have an innocent cause distinct from an edited figure: the reader put
    # a genuinely-printed amount in the wrong column (debit vs credit) — the cross-read confirms the
    # NUMBER at a cell, never which column it was labelled under (§5.2 covers values, not labels). Two
    # independent, template-independent checks recover this without ever asserting a verdict the data
    # doesn't support: `_column_mislabeled_rows` uses this document's own column geometry; `
    # _bbox_free_swap_rows` catches the same failure on rows geometry has no opinion on at all (a reader
    # that dropped box-grounding for a whole page — CLAUDE.md §6, observed in production). Either is
    # real evidence of *something questionable*, but not proof the figure itself was edited — reporting
    # it as confirmed tamper would overstate what was actually established.
    geometric_rows = _column_mislabeled_rows(txns, gate)
    swap_rows = _bbox_free_swap_rows(txns, rows, tuple(confirmed), tol)
    mislabeled_rows = geometric_rows | swap_rows
    clean = [b for b in confirmed if b.index not in mislabeled_rows]
    ambiguous = [b for b in confirmed if b.index in mislabeled_rows]
    if not clean:
        worst = ambiguous[0]
        if worst.index in geometric_rows:
            cause = (
                f"row {worst.index}'s debit/credit column assignment is geometrically inconsistent "
                f"with the rest of this statement's own layout"
            )
        else:
            cause = (
                f"row {worst.index}'s own printed figure exactly reconciles the chain if its debit and "
                f"credit were swapped, and its box grounding is missing so geometry cannot corroborate "
                f"either reading"
            )
        return _not_evaluated_because(
            "F1",
            f"{cause} (expected {worst.expected}, printed {worst.printed}) — the figure may be "
            f"correctly read but mislabeled debit/credit, not necessarily edited; not attributed to "
            f"tampering",
        )

    evidence = tuple(
        _ev("transaction", "running_balance", bal_claims.get(b.index), b) for b in clean
    )
    first = clean[0]
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

    uncounted = _uncounted_movement(txns, gate)
    if uncounted:
        return _not_evaluated_because(
            "F3",
            f"{uncounted} transaction amount(s) could not be independently confirmed — summing only "
            f"the confirmed rows would silently exclude real (unconfirmed) movement, so the column "
            f"total cannot be reliably checked",
        )

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
    uncounted = _uncounted_movement(txns, gate)
    if uncounted:
        return _not_evaluated_because(
            "F4",
            f"{uncounted} transaction amount(s) could not be independently confirmed — summing only "
            f"the confirmed rows would silently exclude real (unconfirmed) movement, so net "
            f"reconciliation cannot be reliably checked",
        )
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
