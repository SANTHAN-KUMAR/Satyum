"""Cross-document consistency graph (ADR-003 innovation pillar #3) — bundle-level tamper signal.

A single forged document can be made individually plausible. What a forger struggles to keep coherent
is the **same identity across a whole application bundle** — the name / PAN / Aadhaar / account number
/ DOB must agree between the bank statement, the ID, and the deed. A mismatch is strong, explainable
fraud evidence ("the name on the ID does not match the name on the statement"), and it is exactly the
kind of *logic* check pixel-forensics cannot make.

This module is the bundle-scoped judgment over the per-document :class:`ExtractedEntities`
(``forensics/entities.py``). It is pure, deterministic graph logic (no ML).

OCR realism (CLAUDE.md §3.3/§4 — a misclassified genuine is a finding): Canara's real borrowers
submit scanned/photographed paper, so a single mis-OCR'd character must NOT masquerade as identity
fraud. Hard-identifier values that differ by a single character of the same length are treated as a
*near-match* ("possible OCR misread") and routed to REVIEW, not a 0.92 REJECT — while a genuinely
different value (many characters apart) stays dispositive. Likewise a name-only disagreement (names
are a soft corroborator, with transliteration variance) is clamped to the REVIEW band, never a hard
reject on its own. Only a true hard-identifier mismatch rejects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.contracts import LayerSignal, Mode
from forensics.entities import ExtractedEntities

# Per-field suspicion for a TRUE hard-identifier disagreement (values far apart). Hard identifiers do
# not legitimately vary between an applicant's own documents. DEFAULT — calibrate on a bundle corpus.
_FIELD_SEVERITY: dict[str, float] = {
    "pan": 0.92,
    "aadhaar": 0.92,
    "dob": 0.85,
    "account_number": 0.85,
    "ifsc": 0.70,
    "name": 0.60,
}
# Residual suspicion when every shared field AGREES — corroboration is positive but not proof.
_AGREEMENT_SUSPICION = 0.04
# The REVIEW-band ceiling: a suspicion at/below this lands the bundle in REVIEW, not REJECT (because
# the bundle score is 100*(1-suspicion) and review_at is the REVIEW floor). Used for OCR near-matches
# and name-only disagreements so neither can hard-reject a genuine applicant.
_REVIEW_CAP_SEVERITY = round(1.0 - settings.review_at / 100.0, 2)

_HARD_IDENTIFIERS = ("pan", "aadhaar", "ifsc", "account_number", "dob")

# Comparison outcomes for a single field across the documents that carry it.
AGREE = "agree"        # all values identical (or name-equivalent)
NEAR = "near"          # hard id differs by a single char of equal length -> likely OCR misread
DISAGREE = "disagree"  # a genuine mismatch


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (small strings — identifiers/surnames). Deterministic, no deps."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class FieldComparison:
    """The cross-document comparison of one field across the documents that carry it."""

    field: str
    status: str             # AGREE | NEAR | DISAGREE
    values: dict[str, str]  # doc_label -> value
    severity: float         # effective suspicion contribution (0.0 when AGREE)

    @property
    def agree(self) -> bool:
        return self.status == AGREE


@dataclass
class CrossDocumentResult:
    comparisons: list[FieldComparison] = field(default_factory=list)
    compared_fields: list[str] = field(default_factory=list)

    @property
    def disagreements(self) -> list[FieldComparison]:
        return [c for c in self.comparisons if c.status != AGREE]

    @property
    def hard_mismatches(self) -> list[FieldComparison]:
        """TRUE hard-identifier mismatches (dispositive) — excludes OCR near-matches and names."""
        return [c for c in self.comparisons
                if c.status == DISAGREE and c.field in _HARD_IDENTIFIERS]


def _token_compatible(t1: str, t2: str) -> bool:
    """Name tokens are compatible if equal, or one is an INITIAL of the other ("J" ~ "JOHN")."""
    if t1 == t2:
        return True
    if len(t1) == 1 and t2.startswith(t1):
        return True
    return len(t2) == 1 and t1.startswith(t2)


def _names_match(a: str, b: str) -> bool:
    """Surname-anchored deterministic name match.

    Requires the SURNAME (last token) to be equal or a single typo apart, THEN aligns the given-name
    tokens of the shorter name to the longer's (initial-aware). This tolerates real variance — missing
    middle name, an initial vs a full first name, whitespace — WITHOUT the fail-open failures of a bare
    similarity ratio (it correctly rejects "A KUMAR" vs "B KUMAR" and "JOHN" vs "JOHN SMITH", which a
    ratio/single-token match wrongly accepted). Given-name typos / transliterations fall through to a
    name *disagreement*, which the caller clamps to REVIEW — a human checks, never an auto-reject.
    """
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return False
    sa, sb = ta[-1], tb[-1]
    if sa != sb and _edit_distance(sa, sb) > 1:  # surnames must match (allow one OCR/typo char)
        return False
    short, long = (ta[:-1], tb[:-1]) if len(ta) <= len(tb) else (tb[:-1], ta[:-1])
    used = [False] * len(long)
    matched = 0
    for t in short:
        for j, u in enumerate(long):
            if not used[j] and _token_compatible(t, u):
                used[j] = True
                matched += 1
                break
    return matched == len(short)


def _compare_field(field_name: str, values: list[str]) -> tuple[str, float]:
    """Classify a field's cross-document values into (status, effective severity)."""
    if field_name == "name":
        if all(_names_match(values[0], v) for v in values[1:]):
            return AGREE, 0.0
        # Names are a soft corroborator (transliteration/typo variance) -> clamp to REVIEW band.
        return DISAGREE, min(_FIELD_SEVERITY["name"], _REVIEW_CAP_SEVERITY)

    distinct = set(values)
    if len(distinct) == 1:
        return AGREE, 0.0
    # Likely OCR misread: all distinct values same length and pairwise within one edit -> REVIEW.
    if _likely_ocr_artifact(distinct):
        return NEAR, _REVIEW_CAP_SEVERITY
    return DISAGREE, _FIELD_SEVERITY.get(field_name, 0.5)


def _likely_ocr_artifact(distinct: set[str]) -> bool:
    vals = list(distinct)
    if len({len(v) for v in vals}) != 1:  # different lengths -> not a single-char slip
        return False
    return all(
        _edit_distance(vals[i], vals[j]) <= 1
        for i in range(len(vals)) for j in range(i + 1, len(vals))
    )


def compare_entities(entities_by_doc: dict[str, ExtractedEntities]) -> CrossDocumentResult:
    """Build the field-by-field cross-document comparison over a bundle of documents."""
    per_field: dict[str, dict[str, str]] = {}
    for doc_label, ent in entities_by_doc.items():
        for fname, fval in ent.comparable_fields().items():
            per_field.setdefault(fname, {})[doc_label] = fval

    result = CrossDocumentResult()
    for fname, doc_values in per_field.items():
        if len(doc_values) < 2:  # only one doc carries it -> nothing to cross-check
            continue
        status, severity = _compare_field(fname, list(doc_values.values()))
        result.comparisons.append(
            FieldComparison(field=fname, status=status, values=dict(doc_values), severity=severity)
        )
        result.compared_fields.append(fname)
    return result


def cross_document_signal(entities_by_doc: dict[str, ExtractedEntities]) -> LayerSignal:
    """Produce the bundle-level cross-document consistency :class:`LayerSignal`.

    NOT_EVALUATED when no field is shared by >=2 documents (nothing to compare — never a fake pass).
    VALID otherwise: suspicion driven by the most severe disagreement, or near-zero if all agree. A
    hard-identifier mismatch is dispositive; an OCR near-match or a name-only disagreement is clamped
    to the REVIEW band (never an auto-reject of a genuine applicant).
    """
    name, layer, mode = "cross_document_consistency", 2, Mode.FILE
    result = compare_entities(entities_by_doc)

    if not result.comparisons:
        return LayerSignal.not_evaluated(
            name, layer, mode,
            "fewer than two documents share a comparable identity field — cannot cross-check",
            documents=len(entities_by_doc),
        )

    disagreements = result.disagreements
    measurements: dict = {
        "compared_fields": result.compared_fields,
        "documents": len(entities_by_doc),
        "comparisons": [
            {"field": c.field, "status": c.status, "agree": c.agree, "values": c.values}
            for c in result.comparisons
        ],
        "disagreeing_fields": [c.field for c in disagreements],
        "hard_mismatch_fields": [c.field for c in result.hard_mismatches],
        "near_match_fields": [c.field for c in result.comparisons if c.status == NEAR],
    }
    # A TRUE hard-identifier mismatch (PAN/Aadhaar/account/IFSC/DOB differ across an applicant's own
    # documents) is dispositive identity fraud — flag it as a hard-reject trigger so the decision brain
    # (ADR-004 §7 golden rule #5) rejects fail-closed even if this signal ever reaches a single-document
    # aggregate. The bundle aggregator independently floors on the same evidence (defence in depth).
    if result.hard_mismatches:
        measurements["hard_reject"] = True

    if not disagreements:
        return LayerSignal.valid(
            name, layer, mode,
            suspicion=_AGREEMENT_SUSPICION,
            weight=settings.weight_cross_document,
            reason=(f"identity consistent across {len(entities_by_doc)} documents on "
                    f"{', '.join(result.compared_fields)} — bundle corroborates"),
            measurements=measurements,
        )

    worst = max(disagreements, key=lambda c: c.severity)
    detail = "; ".join(
        f"{c.field}[{c.status}]: " + " vs ".join(f"{d}={v!r}" for d, v in c.values.items())
        for c in disagreements
    )
    pair = list(worst.values.items())
    if result.hard_mismatches:
        headline = (
            f"identity MISMATCH across documents — {worst.field} differs "
            f"({pair[0][0]}={pair[0][1]!r} vs {pair[1][0]}={pair[1][1]!r}); "
            f"hard-identifier mismatch on {', '.join(c.field for c in result.hard_mismatches)}"
        )
    elif any(c.status == NEAR for c in disagreements):
        headline = (
            f"possible OCR misread on {worst.field} "
            f"({pair[0][0]}={pair[0][1]!r} vs {pair[1][0]}={pair[1][1]!r}) — manual review"
        )
    else:
        headline = (
            f"name differs across documents "
            f"({pair[0][0]}={pair[0][1]!r} vs {pair[1][0]}={pair[1][1]!r}) — soft signal, manual review"
        )
    return LayerSignal.valid(
        name, layer, mode,
        suspicion=worst.severity,
        weight=settings.weight_cross_document,
        reason=f"{headline}. Details: {detail}",
        measurements=measurements,
    )
