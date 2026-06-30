"""Discrimination tests for the Indian/English number-word parser (rules/numwords.py).

The §3.1 self-test in the small: a DIFFERENT word phrase must yield a DIFFERENT number (so the parser
actually reads the words, not a constant), and unparseable wording must yield ``None`` (NOT_EVALUATED
downstream), never a fabricated value. This is the engine behind the legal pack's words-vs-figures
tamper check, so its correctness is load-bearing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rules.numwords import words_to_decimal


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Rupees Twelve Lakh Fifty Thousand Only", "1250000"),
        ("One Crore Twenty Lakh", "12000000"),
        ("Two Thousand Five Hundred", "2500"),
        ("Fifty Thousand Five Hundred and Twenty Five", "50525"),
        ("Rupees Five Lakh Only", "500000"),
        ("Rupees One Thousand and Fifty Paise Only", "1000.50"),
        ("Ninety Nine", "99"),
        ("Ten Lakh", "1000000"),
    ],
)
def test_words_parse_to_the_right_number(phrase, expected):
    assert words_to_decimal(phrase) == Decimal(expected)


def test_a_different_phrase_yields_a_different_number():
    # would FAIL against a constant return: the value tracks the words.
    assert words_to_decimal("Five Lakh") != words_to_decimal("Six Lakh")
    assert words_to_decimal("One Lakh Fifty Thousand") == Decimal("150000")


@pytest.mark.parametrize("junk", ["", "garbage words here", "the and of only", "Schedule A"])
def test_unparseable_wording_is_none_never_a_fake_value(junk):
    assert words_to_decimal(junk) is None


def test_lakh_and_crore_scales_compose():
    # the Indian scale words must compose left-to-right, not collapse.
    assert words_to_decimal("Two Crore Fifty Lakh Seventy Five Thousand") == Decimal("25075000")
