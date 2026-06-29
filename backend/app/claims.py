"""The canonical claim graph (ADR-004 Layer 3) — the contract that decouples reading from judging.

The VLM (Layer 2) reads *any* layout into a flat set of typed :class:`Claim`s; the deterministic
rule packs (Layer 4) and corroboration (Layer 6) then operate on this single structure instead of one
hardcoded table layout. SBI, Canara, a phone photo of a deed, a vernacular RoR — all collapse to the
same typed claims, so the rules are template-independent.

The integrity spine lives in :class:`ClaimProvenance`: every value carries *where it came from*
(doc/page/bbox), *how confident the reader was*, and — for the numbers a forger edits — *whether an
independent deterministic OCR re-read agreed* (``cross_read_agree``, ADR-004 §5.2). A claim whose
cross-read disagreed, or whose confidence is below the gate, is **never silently trusted**: the
``is_trusted`` gate returns ``False`` and Layer 4 carries it as ``NOT_EVALUATED``/pending.

These are Pydantic models (not the in-memory ``AnalysisContext`` dataclass) because the claim graph is
serialised into the evidence pack, the API contract, and the tamper-evident audit (CLAUDE.md §11).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

# Pixel-space box (x, y, w, h) in the rendered page image — the same convention as
# ``EvidenceRegion`` and the arithmetic engine, so a claim's box overlays the document directly.
BBox = tuple[float, float, float, float]


class ClaimProvenance(BaseModel):
    """Where a claim's value came from and how it was verified — the auditor's reconstruction.

    A bank auditor asking "why 85,000?" gets exactly this: the document + page, the box at ``bbox``,
    the reader's ``confidence``, and — for a number — the independent OCR ``corroborating_read`` and
    whether the two agreed. ``source`` records the producing reader (e.g. ``"vlm:claude-..."``) so the
    extraction context is reconstructable from the audit chain (ADR-004 §5.6).
    """

    doc_id: str
    page: int = 0
    bbox: BBox | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str  # the reader that produced the value, e.g. "vlm:claude-sonnet-4-6"

    # --- the cross-read consensus result (ADR-004 §5.2), set only for cross-read-critical numbers ---
    corroborating_read: str | None = None  # the deterministic OCR's independent read of this cell
    cross_read_agree: bool = False  # did the OCR re-read match the VLM value within tolerance?
    cross_read_detail: str = ""  # human-readable note: which engines, what they read, why (dis)agree


class Claim(BaseModel):
    """One typed, box-grounded assertion the document makes — never a judgement about it.

    ``subject``/``predicate``/``value`` is the triple (e.g. ``("account_1", "closing_balance",
    "84200.00")``); ``value_type`` names the ontology type (``Money``, ``Date``, ``PersonName``, …)
    that decides how the value is validated and matched. ``index`` orders rows of an ordered entity
    (a transaction's row number). ``cross_read_required`` is set from the ontology
    (``cross_read_critical`` types) so the trust gate knows which claims must clear the OCR re-read.
    """

    subject: str
    predicate: str
    value: str  # canonical normalised string (Decimal text for money, ISO-ish for dates) — exact + JSON-safe
    value_type: str
    index: int | None = None  # row index within an ordered entity (e.g. Transaction), else None
    cross_read_required: bool = False
    provenance: ClaimProvenance

    def as_decimal(self) -> Decimal | None:
        """The value as a ``Decimal`` if it parses, else ``None`` (never a guessed 0)."""
        try:
            return Decimal(self.value)
        except (InvalidOperation, ValueError, TypeError):
            return None

    def is_trusted(self, min_confidence: float) -> bool:
        """Whether a deterministic rule may consume this claim's value as fact.

        A claim is trusted only if the reader cleared the confidence gate AND — for the numbers a
        forger edits — the independent OCR cross-read agreed. This is the structural guarantee that a
        VLM hallucination (or a laundered tamper) cannot reach a rule as a clean number (ADR-004 §5.2):
        disagreement ⇒ untrusted ⇒ Layer 4 treats it as ``NOT_EVALUATED``, never a silent pick.
        """
        if self.provenance.confidence < min_confidence:
            return False
        if self.cross_read_required and not self.provenance.cross_read_agree:
            return False
        return True


class ClaimGraph(BaseModel):
    """Every claim extracted from a document (and, later, across the bundle), with query helpers.

    Layer 4 (rule packs) and Layer 6 (corroboration) are written as queries over this graph — e.g.
    "the ordered series of ``Transaction.running_balance``" or "every ``holder_name`` across the
    bundle". Keeping the helpers here means the rules never re-implement claim filtering.
    """

    doc_id: str
    doc_type: str | None = None
    primary_language: str | None = None  # the dominant script/language the reader detected (audit + routing)
    claims: list[Claim] = Field(default_factory=list)

    def add(self, claim: Claim) -> None:
        self.claims.append(claim)

    def by_predicate(self, predicate: str) -> list[Claim]:
        """All claims with this predicate, ordered by ``index`` (rows in document order) then insertion."""
        hits = [c for c in self.claims if c.predicate == predicate]
        return sorted(hits, key=lambda c: c.index if c.index is not None else -1)

    def by_subject(self, subject: str) -> list[Claim]:
        return [c for c in self.claims if c.subject == subject]

    def first(self, predicate: str) -> Claim | None:
        """The single claim for a scalar predicate (e.g. ``closing_balance``), or ``None``."""
        hits = self.by_predicate(predicate)
        return hits[0] if hits else None

    def numeric_claims(self) -> list[Claim]:
        """Claims whose type is cross-read-critical (the numbers the OCR consensus must confirm)."""
        return [c for c in self.claims if c.cross_read_required]

    def cross_read_failures(self) -> list[Claim]:
        """Cross-read-critical claims whose independent OCR re-read did NOT agree — pending, not trusted.

        These are the cells where the VLM and the deterministic OCR disagree: either a tamper one
        reader smoothed, or an unreadable figure. Surfaced to the console + the decision brain so a
        critical disagreement routes to REVIEW (fail-closed), never to a silent APPROVE.
        """
        return [c for c in self.numeric_claims() if not c.provenance.cross_read_agree]

    def trusted(self, min_confidence: float) -> list[Claim]:
        return [c for c in self.claims if c.is_trusted(min_confidence)]

    def cross_read_agreement_rate(self) -> float | None:
        """Fraction of cross-read-critical claims that the OCR confirmed, or ``None`` if there are none."""
        numeric = self.numeric_claims()
        if not numeric:
            return None
        agreed = sum(1 for c in numeric if c.provenance.cross_read_agree)
        return agreed / len(numeric)
