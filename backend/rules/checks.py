"""The finite ``check_kinds`` catalog (_shared.json) as pure, deterministic functions (ADR-004 §4).

Each function recomputes one kind of invariant over already-resolved numeric inputs and returns a
:class:`CheckOutcome`. There is deliberately **no arbitrary expression evaluation** — a rule can only
dispatch to one of these named, audited primitives. The ``linear_balance`` chain is lifted verbatim in
spirit from the proven ``forensics/arithmetic.py`` engine (the re-anchoring that makes one edit break
*locally*, not cascade), now operating on claim-graph values instead of one hardcoded table layout.

Pure: no I/O, no config, no claim-graph knowledge — inputs in, outcome out. Directly unit-tested.
"""

from __future__ import annotations

import operator
from datetime import date
from decimal import Decimal
from typing import Any

from rules.contracts import Break, CheckOutcome


def _close(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    return (a - b).copy_abs() <= tol


def linear_balance(
    anchor: Decimal | None,
    rows: list[tuple[int, Decimal | None, Decimal | None, Decimal | None]],
    tol: Decimal,
) -> CheckOutcome:
    """Running balance carries forward: ``balance[i] = balance[i-1] + credit[i] - debit[i]`` (F1).

    ``rows`` is ``(index, credit, debit, printed_balance)`` in document order. For each row with a
    printed balance we compare it to the expected value and then **re-anchor on the printed figure** —
    so a single edited cell breaks at its own row (and the next), never cascading into a false storm of
    downstream breaks. Insufficient (no opening anchor, <2 printed balances, or no movement) ⇒ the rule
    is NOT_EVALUATED, never a fabricated pass — exactly the honest bound of the original engine.

    A row with no printed balance (its cross-read didn't confirm it — e.g. an ungrounded VLM box, common
    when a whole page's grounding degrades) is not compared; its movement is silently folded into
    ``expected`` and carried forward uncompared. Each :class:`Break` records ``unconfirmed_run`` — how
    many such uncompared rows immediately preceded it. A break with ``unconfirmed_run == 0`` sits right
    after a confirmed row: a genuine single-cell edit, unambiguous tamper evidence. A break with a large
    ``unconfirmed_run`` means the mismatch may just be the accumulated, unverifiable movement of an
    unconfirmed run — real evidence of *something unread*, but not proof of an edited figure. The caller
    (F1) uses this to avoid reporting an extraction gap as tampering (CLAUDE.md §3.3).
    """
    printed_count = sum(1 for _, _, _, p in rows if p is not None)
    movement_count = sum(1 for _, c, d, _ in rows if c is not None or d is not None)
    if anchor is None or printed_count < 2 or movement_count < 1:
        return CheckOutcome.insufficient()

    breaks: list[Break] = []
    checks = 0
    running = anchor
    unconfirmed_run = 0
    for index, credit, debit, printed in rows:
        expected = running + (credit or Decimal(0)) - (debit or Decimal(0))
        if printed is not None:
            checks += 1
            if not _close(expected, printed, tol):
                breaks.append(
                    Break(expected=expected, printed=printed, index=index, unconfirmed_run=unconfirmed_run)
                )
            running = printed  # re-anchor on the printed figure (local break, not cascading)
            unconfirmed_run = 0
        else:
            running = expected
            unconfirmed_run += 1
    return CheckOutcome(evaluated=True, breaks=tuple(breaks), checks_run=checks)


def equation(terms: list[tuple[int, Decimal | None]], rhs: Decimal | None, tol: Decimal) -> CheckOutcome:
    """``sum(coef_i * value_i) == rhs`` within tolerance (F2/F4/F6).

    Any missing term or rhs ⇒ insufficient (NOT_EVALUATED). On a break, ``expected`` is the computed
    left-hand side and ``printed`` is the stated right-hand side (what the document claims).
    """
    if rhs is None or any(value is None for _, value in terms):
        return CheckOutcome.insufficient()
    lhs = sum((Decimal(coef) * value for coef, value in terms), Decimal(0))  # type: ignore[operator]
    if _close(lhs, rhs, tol):
        return CheckOutcome(evaluated=True, checks_run=1)
    return CheckOutcome(evaluated=True, breaks=(Break(expected=lhs, printed=rhs),), checks_run=1)


def sum_equals(series: list[Decimal], stated: Decimal | None, tol: Decimal) -> CheckOutcome:
    """``sum(series) == stated`` within tolerance (F3). ``stated`` missing ⇒ insufficient."""
    if stated is None:
        return CheckOutcome.insufficient()
    total = sum(series, Decimal(0))
    if _close(total, stated, tol):
        return CheckOutcome(evaluated=True, checks_run=1)
    return CheckOutcome(evaluated=True, breaks=(Break(expected=total, printed=stated),), checks_run=1)


_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def comparison(left: Decimal | None, op: str, right: Decimal | None) -> CheckOutcome:
    """``left op right`` (F7). Either side missing ⇒ insufficient. A failed comparison is one break."""
    if left is None or right is None:
        return CheckOutcome.insufficient()
    fn = _OPS.get(op)
    if fn is None:
        raise ValueError(f"unsupported comparison operator {op!r}")
    if fn(left, right):
        return CheckOutcome(evaluated=True, checks_run=1)
    return CheckOutcome(
        evaluated=True,
        breaks=(Break(expected=right, printed=left, detail=f"{left} {op} {right} is false"),),
        checks_run=1,
    )


def _add_months(d: date, months: int) -> date:
    """Add a (possibly large) month count to a date, clamping the day to the target month's length."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # Clamp the day (e.g. 31 Jan + 1 month -> 28/29 Feb). Last day of the target month:
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(d.day, last_day))


def date_within(d: date | None, after: date | None, max_months: int) -> CheckOutcome:
    """``after <= d <= after + max_months`` (e.g. registration within 4 months of execution, RA 1908).

    Either date missing ⇒ insufficient. A break carries the offending date and the legal window so the
    underwriter sees exactly what failed.
    """
    if d is None or after is None:
        return CheckOutcome.insufficient()
    deadline = _add_months(after, max_months)
    if after <= d <= deadline:
        return CheckOutcome(evaluated=True, checks_run=1)
    detail = f"{d.isoformat()} not within [{after.isoformat()}, {deadline.isoformat()}]"
    return CheckOutcome(evaluated=True, breaks=(Break(detail=detail),), checks_run=1)


def date_offset_equals(
    start: date | None, months: int | None, end: date | None, tol_days: int
) -> CheckOutcome:
    """``start + months == end`` within ``tol_days`` (e.g. effective date + term = end date)."""
    if start is None or months is None or end is None:
        return CheckOutcome.insufficient()
    expected = _add_months(start, months)
    if abs((end - expected).days) <= tol_days:
        return CheckOutcome(evaluated=True, checks_run=1)
    detail = f"expected end {expected.isoformat()} (start + {months}mo), printed {end.isoformat()}"
    return CheckOutcome(evaluated=True, breaks=(Break(detail=detail),), checks_run=1)


def date_order(left: date | None, op: str, right: date | None) -> CheckOutcome:
    """``date(left) op date(right)`` for ``<,<=,>,>=,==`` (e.g. registration cannot precede execution)."""
    if left is None or right is None:
        return CheckOutcome.insufficient()
    fn = _OPS.get(op)
    if fn is None:
        raise ValueError(f"unsupported date operator {op!r}")
    if fn(left, right):
        return CheckOutcome(evaluated=True, checks_run=1)
    return CheckOutcome(
        evaluated=True,
        breaks=(Break(detail=f"{left.isoformat()} {op} {right.isoformat()} is false"),),
        checks_run=1,
    )


def set_subset(subset_keys: list[str] | None, superset_keys: list[str] | None) -> CheckOutcome:
    """Every key in ``subset_keys`` must appear in ``superset_keys`` (e.g. EC encumbrances ⊆ deed).

    ``subset_keys`` empty ⇒ vacuously true (PASS); ``superset_keys`` ``None`` ⇒ insufficient.
    """
    if superset_keys is None or subset_keys is None:
        return CheckOutcome.insufficient()
    missing = [k for k in subset_keys if k not in set(superset_keys)]
    if not missing:
        return CheckOutcome(evaluated=True, checks_run=max(1, len(subset_keys)))
    return CheckOutcome(
        evaluated=True,
        breaks=(Break(detail=f"not disclosed in superset: {', '.join(missing)}"),),
        checks_run=len(subset_keys),
    )


def references_resolve(refs: list[str] | None, targets: list[str] | None) -> CheckOutcome:
    """Every reference token must resolve to an existing target key (e.g. each cited schedule exists)."""
    if refs is None or targets is None:
        return CheckOutcome.insufficient()
    if not refs:
        return CheckOutcome.insufficient()
    target_set = {t.strip().lower() for t in targets}
    unresolved = [r for r in refs if r.strip().lower() not in target_set]
    if not unresolved:
        return CheckOutcome(evaluated=True, checks_run=len(refs))
    return CheckOutcome(
        evaluated=True,
        breaks=(Break(detail=f"unresolved reference(s): {', '.join(unresolved)}"),),
        checks_run=len(refs),
    )


def presence_count(count: int | None, minimum: int, exact: int | None = None) -> CheckOutcome:
    """The number of present instances meets ``minimum`` (and ``exact`` if given). ``None`` ⇒ insufficient."""
    if count is None:
        return CheckOutcome.insufficient()
    ok = count >= minimum and (exact is None or count == exact)
    if ok:
        return CheckOutcome(evaluated=True, checks_run=1)
    want = f"exactly {exact}" if exact is not None else f">= {minimum}"
    return CheckOutcome(
        evaluated=True,
        breaks=(Break(detail=f"present count {count}, required {want}"),),
        checks_run=1,
    )


def sequence_complete(numbers: list[int] | None, start: int, expected_count: int | None) -> CheckOutcome:
    """The integers form a complete run ``start..start+expected_count-1`` with no gaps or duplicates.

    Used for page-number completeness (G5). ``numbers`` ``None``/empty or ``expected_count`` ``None`` ⇒
    insufficient (we cannot assert completeness without a declared page count).
    """
    if not numbers or expected_count is None:
        return CheckOutcome.insufficient()
    expected = list(range(start, start + expected_count))
    got = sorted(numbers)
    if got == expected:
        return CheckOutcome(evaluated=True, checks_run=expected_count)
    missing = sorted(set(expected) - set(got))
    dupes = sorted({n for n in got if got.count(n) > 1})
    parts = []
    if missing:
        parts.append(f"missing pages {missing}")
    if dupes:
        parts.append(f"duplicate pages {dupes}")
    if not parts:
        parts.append(f"page set {got} != expected {expected}")
    return CheckOutcome(evaluated=True, breaks=(Break(detail="; ".join(parts)),), checks_run=expected_count)


def sequence_monotonic(series: list[tuple[int, Any | None]], strict: bool) -> CheckOutcome:
    """The present values of ``series`` are non-decreasing (``strict`` ⇒ strictly increasing) (F5).

    ``series`` is ``(index, comparable | None)`` in document order; ``None`` values are skipped. Fewer
    than two present values ⇒ insufficient. Breaks at the first out-of-order index.
    """
    present = [(idx, val) for idx, val in series if val is not None]
    if len(present) < 2:
        return CheckOutcome.insufficient()
    breaks: list[Break] = []
    prev_val = present[0][1]
    for idx, val in present[1:]:
        out_of_order = (val <= prev_val) if strict else (val < prev_val)
        if out_of_order:
            breaks.append(Break(index=idx, detail=f"value at row {idx} is out of order"))
        prev_val = val
    return CheckOutcome(evaluated=True, breaks=tuple(breaks), checks_run=len(present) - 1)
