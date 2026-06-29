"""Deterministic number-word → Decimal parser (the legal pack's ``words_equal_figures`` primitive).

The classic deterministic tamper check on a deed or agreement: the consideration is written **both** in
figures ("₹12,50,000") and in words ("Rupees Twelve Lakh Fifty Thousand Only"). A forger who edits the
figure almost never re-renders the matching words, so a figures-vs-words mismatch is strong, explainable
evidence of an edit — and it is pure logic, no ML (CLAUDE.md §3.1/§6).

This parses the Indian English number-word system (lakh = 10^5, crore = 10^7) as well as the
international hundred/thousand scales, which is what real Indian instruments use. It is intentionally
strict: unparseable / unknown wording returns ``None`` (the rule is then NOT_EVALUATED, never a guessed
pass), and a different word phrase yields a different number (the §3.1 self-test holds).

Honest bound: words like "fifty thousand five hundred and twenty-five" parse; free-form or vernacular
(Devanagari) numerals do not — they return ``None`` and route to NOT_EVALUATED rather than a fake value.
"""

from __future__ import annotations

import re
from decimal import Decimal

# Token → value. Units and tens are additive; hundred multiplies the current group; thousand/lakh/crore
# flush the current group into the running total at their scale (left-to-right, the natural reading).
_UNITS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_HUNDRED = "hundred"
_SCALES: dict[str, int] = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000,
                           "crore": 10_000_000, "crores": 10_000_000}

# Filler words stripped before parsing (currency framing / connectors / punctuation).
_FILLER = {"rupees", "rupee", "rs", "inr", "only", "and", "of", "the"}
_TOKEN_RE = re.compile(r"[a-z]+")


def _tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower().replace("-", " ")) if t not in _FILLER]


def _group_to_number(tokens: list[str]) -> int | None:
    """Reduce a token list to an integer via the standard additive/scale algorithm.

    Returns ``None`` if a non-number token appears (so a phrase that is not actually a number-amount is
    rejected rather than silently treated as a partial value).
    """
    total = 0
    current = 0
    saw_number = False
    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]
            saw_number = True
        elif tok in _TENS:
            current += _TENS[tok]
            saw_number = True
        elif tok == _HUNDRED:
            current = (current or 1) * 100
            saw_number = True
        elif tok in _SCALES:
            total += (current or 1) * _SCALES[tok]
            current = 0
            saw_number = True
        else:
            return None  # an unknown token -> not a clean number phrase
    if not saw_number:
        return None
    return total + current


def words_to_decimal(text: str) -> Decimal | None:
    """Parse an Indian/English rupee amount in words to a ``Decimal`` (rupees, with optional paise).

    Recognises an optional ``... paise <words>`` fractional tail. Returns ``None`` if the rupee part is
    not a clean number phrase — the caller then reports NOT_EVALUATED, never a fabricated figure.
    """
    if not text:
        return None
    lower = text.lower()

    # "<rupees words> [and] <paise words> paise": the paise number PRECEDES the word "paise", so split
    # the head before "paise" on its final "and" — the tail is paise, the head is rupees.
    rupee_part, paise_part = lower, ""
    if re.search(r"\bpaise?\b", lower):
        head = re.split(r"\bpaise?\b", lower, maxsplit=1)[0]
        # The paise number is the words after the FINAL "and"; everything before is rupees.
        if " and " in head:
            rupee_part, paise_part = head.rsplit(" and ", 1)
        else:
            rupee_part, paise_part = "", head

    rupees = _group_to_number(_tokenise(rupee_part))
    paise = _group_to_number(_tokenise(paise_part)) if paise_part.strip() else None
    if rupees is None and paise is None:
        return None
    value = Decimal(rupees or 0)
    if paise is not None and 0 <= paise < 100:
        value += Decimal(paise) / Decimal(100)
    return value
