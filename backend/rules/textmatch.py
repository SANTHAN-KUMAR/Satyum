"""Shared string-matching helpers for the deterministic rule packs (land/legal fuzzy primitives).

The land and legal packs compare *names* (deed seller vs RoR owner; a party across recital/signature/
schedule) and *generic tokens* (schedule labels, clause references). Person names carry real, benign
variance — a missing middle name, an initial vs a full first name, a transliteration — so an exact match
is wrong (it would reject genuine documents) and a bare similarity ratio is also wrong (it fail-opens on
"A Kumar" vs "B Kumar"). We reuse the proven surname-anchored matcher from the cross-document graph
(``forensics/cross_document``) rather than re-implement it, and add a normalised Levenshtein ratio for
non-name tokens. Pure + deterministic (CLAUDE.md §6 — real techniques, no ML).
"""

from __future__ import annotations

import re

from forensics.cross_document import _edit_distance, _names_match

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(s: str) -> str:
    """Lower-case, replace runs of non-alphanumerics with a single space, and trim."""
    return _NON_ALNUM.sub(" ", s.lower()).strip()


def text_ratio(a: str, b: str) -> float:
    """Normalised Levenshtein similarity in [0,1] for non-name tokens (labels, references)."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return 1.0 - _edit_distance(na, nb) / max(len(na), len(nb))


def names_agree(a: str, b: str) -> bool:
    """Surname-anchored person-name agreement (tolerant of initials/middle names, strict on surname).

    Delegates to the cross-document graph's matcher so identity logic stays in one place. The ontology's
    per-rule ``min_ratio`` (0.85/0.90) is realised by that matcher's token alignment rather than a raw
    ratio, which is the more robust criterion (it does not fail-open on equal-length different names).
    """
    return _names_match(normalize_text(a).upper(), normalize_text(b).upper())


def all_names_agree(names: list[str]) -> tuple[bool, tuple[str, str] | None]:
    """True iff every name pairwise agrees; otherwise the first disagreeing (a, b) pair for evidence."""
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if not names_agree(names[i], names[j]):
                return False, (names[i], names[j])
    return True, None
