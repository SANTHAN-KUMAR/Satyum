"""Discrimination tests for the land/legal check primitives added to rules/checks.py.

Each primitive is pure (resolved inputs in, CheckOutcome out). The tests prove a genuine case PASSES and
a violated case FAILS with a localised break, and that missing inputs yield ``insufficient`` (→
NOT_EVALUATED), never a fabricated pass. They would FAIL against a constant-returning implementation.
"""

from __future__ import annotations

from datetime import date

from rules.checks import (
    _add_months,
    date_offset_equals,
    date_order,
    date_within,
    presence_count,
    references_resolve,
    sequence_complete,
    set_subset,
)


def test_add_months_clamps_day_to_month_length():
    assert _add_months(date(2020, 1, 31), 1) == date(2020, 2, 29)  # leap year
    assert _add_months(date(2021, 1, 31), 1) == date(2021, 2, 28)
    assert _add_months(date(2020, 1, 1), 12) == date(2021, 1, 1)


def test_date_within_passes_inside_window_fails_outside():
    execution = date(2020, 1, 1)
    assert date_within(date(2020, 3, 1), execution, 4).passed          # within 4 months
    assert date_within(date(2020, 5, 1), execution, 4).passed          # exactly 4 months — inclusive
    assert date_within(date(2020, 6, 1), execution, 4).breaks          # past the 4-month deadline
    assert date_within(date(2019, 12, 1), execution, 4).breaks          # registration BEFORE execution
    assert not date_within(None, execution, 4).evaluated                # missing -> insufficient


def test_date_offset_equals_discriminates():
    start = date(2020, 1, 1)
    assert date_offset_equals(start, 12, date(2021, 1, 1), 1).passed
    assert date_offset_equals(start, 12, date(2021, 6, 1), 1).breaks
    assert not date_offset_equals(start, None, date(2021, 1, 1), 1).evaluated


def test_date_order():
    assert date_order(date(2020, 1, 1), "<=", date(2020, 1, 2)).passed
    assert date_order(date(2020, 2, 1), "<=", date(2020, 1, 2)).breaks
    assert not date_order(None, "<=", date(2020, 1, 2)).evaluated


def test_set_subset_detects_undisclosed_items():
    assert set_subset(["enc1"], ["enc1", "enc2"]).passed                # disclosed
    out = set_subset(["enc1", "enc3"], ["enc1", "enc2"])                # enc3 not disclosed
    assert out.breaks and "enc3" in out.breaks[0].detail
    assert set_subset([], ["enc1"]).passed                              # vacuously true
    assert not set_subset(["x"], None).evaluated


def test_references_resolve_detects_dangling_reference():
    assert references_resolve(["Schedule A"], ["Schedule A", "Schedule B"]).passed
    out = references_resolve(["Schedule C"], ["Schedule A"])
    assert out.breaks and "schedule c" in out.breaks[0].detail.lower()
    assert not references_resolve([], ["Schedule A"]).evaluated         # no references -> insufficient


def test_presence_count():
    assert presence_count(2, 2).passed
    assert presence_count(1, 2).breaks
    assert presence_count(3, 1, exact=2).breaks                         # exact mismatch
    assert not presence_count(None, 1).evaluated


def test_sequence_complete_detects_missing_and_duplicate_pages():
    assert sequence_complete([1, 2, 3], 1, 3).passed
    missing = sequence_complete([1, 3], 1, 3)
    assert missing.breaks and "missing" in missing.breaks[0].detail
    dup = sequence_complete([1, 2, 2], 1, 3)
    assert dup.breaks and "duplicate" in dup.breaks[0].detail
    assert not sequence_complete([], 1, None).evaluated
