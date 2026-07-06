"""The ``VLMExtractor`` contract and the typed data it exchanges (ADR-004 Layer 2).

The orchestrator depends on this interface, never on a concrete model SDK (Dependency Inversion,
CLAUDE.md §4): swapping Claude → Gemini → a self-hosted Qwen2.5-VL, or routing vernacular documents to
an Indic specialist, is a config/registry change, not a code rewrite. Every implementation:

  * receives a rendered :class:`PageImage` (pixels + dimensions + any text layer);
  * returns a :class:`RawExtraction` — *transcription only*, typed and bounded, never a judgement;
  * reports a normalised ``bbox`` (``[x, y, w, h]`` in ``[0, 1]``) and ``confidence`` for every value,
    because Layer 2's safety rests on grounding + the deterministic cross-read of those boxes (§5.2).

The extractor has **zero decision authority**: there is deliberately no field in any type below by
which it could mark a document genuine/fake or move a verdict (ADR-004 §2, §5.3). It emits claims; the
deterministic layers decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

# A normalised box: (x, y, w, h) each in [0, 1], relative to the page image. Normalised (not pixels)
# so the same extraction is valid regardless of the DPI we rendered at; the builder converts to pixels.
NormBBox = tuple[float, float, float, float]


class VLMUnavailable(RuntimeError):
    """The extractor cannot run because it is not configured (e.g. no API key, no endpoint).

    A genuine *gate*, not a failure: the analyzer maps it to ``NOT_EVALUATED`` (honest pending), never
    a fabricated pass (CLAUDE.md §3.4). Distinct from :class:`VLMExtractionError`, which is a real
    fault during an attempted extraction and fails closed to ``ERROR``/REVIEW.
    """


class VLMExtractionError(RuntimeError):
    """An attempted extraction failed (network/timeout/malformed response). Fail-closed → ERROR."""


@dataclass(frozen=True)
class PageImage:
    """One rendered document page: the pixels every reader sees, plus what we know deterministically.

    ``png_bytes`` is the rendered raster (PNG); ``width``/``height`` are its pixel dimensions, used to
    convert a normalised ``bbox`` into a pixel crop for the OCR cross-read. ``text_layer`` is the PDF's
    embedded text when present (empty for scans/images) — a free, deterministic signal for script
    detection and routing that needs no OCR. ``text_words`` is the PDF's per-word geometry — each
    ``(bbox, text)`` with ``bbox`` normalised ``[x, y, w, h]`` in ``[0, 1]`` — the *exact* printed
    content the renderer drew, used as the authoritative independent cross-read on a digital-native PDF
    (no OCR loss, no dependence on the VLM box being pixel-precise; empty for scans/images, which fall
    back to the OCR cross-read). Immutable: an intake artifact is read-only (CLAUDE.md §5).
    """

    png_bytes: bytes
    width: int
    height: int
    page_index: int = 0
    text_layer: str = ""
    text_words: tuple[tuple[NormBBox, str], ...] = ()


def _validate_norm_bbox(v: NormBBox | None) -> NormBBox | None:
    # §5.4 hostile-input validation: a box must lie within the page. A malformed/out-of-page box
    # (including raw pixel coordinates a reader emitted instead of a normalised one — e.g. (263.0,
    # 193.0, 281.0, 340.0)) is dropped to None here (the value survives but ungrounded → it cannot
    # pass the cross-read, and downstream page-presence recovery still applies for cross-read-critical
    # types). Shared by every extracted-value shape — a scalar field is exactly as hostile as a
    # transaction cell and must be held to the same box-grounding discipline.
    if v is None:
        return None
    x, y, w, h = v
    if any(not (0.0 <= c <= 1.0) for c in (x, y, w, h)):
        return None
    if w <= 0.0 or h <= 0.0 or x + w > 1.0 + 1e-6 or y + h > 1.0 + 1e-6:
        return None
    return v


class ExtractedValue(BaseModel):
    """A single transcribed value with its grounding — the atom the cross-read re-verifies."""

    value: str
    bbox: NormBBox | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("bbox")
    @classmethod
    def _bbox_in_unit_square(cls, v: NormBBox | None) -> NormBBox | None:
        return _validate_norm_bbox(v)


class ExtractedField(BaseModel):
    """A scalar field the document states (bank name, IFSC, opening balance, net pay, …).

    ``predicate`` is constrained to the known vocabulary (``schema.FIELD_PREDICATES``); the builder
    derives the ontology ``value_type`` and the cross-read requirement from it — the extractor never
    gets to assert a value's type, shrinking the hostile surface (§5.4).
    """

    predicate: str
    value: str
    page: int = 0
    bbox: NormBBox | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("bbox")
    @classmethod
    def _bbox_in_unit_square(cls, v: NormBBox | None) -> NormBBox | None:
        return _validate_norm_bbox(v)


class ExtractedTransaction(BaseModel):
    """One ordered statement row. Each cell is optional (a row may have only a debit or a credit)."""

    seq: int
    posted_on: ExtractedValue | None = None
    value_date: ExtractedValue | None = None
    description: ExtractedValue | None = None
    debit: ExtractedValue | None = None
    credit: ExtractedValue | None = None
    running_balance: ExtractedValue | None = None


class ExtractedSummaryRow(BaseModel):
    """A printed summary line (opening / closing / total_debits / total_credits / grand_total)."""

    kind: str
    amount: ExtractedValue


class RawExtraction(BaseModel):
    """The whole, validated transcription of one document page — the extractor's only product.

    Note what is absent by construction: no verdict, no score, no "genuine"/"fake", no expected value.
    The extractor cannot express a decision; it can only report what it read (ADR-004 §2). Layers 4/6/7
    turn this into a verdict, deterministically.
    """

    doc_type: str
    primary_language: str = "en"
    fields: list[ExtractedField] = Field(default_factory=list)
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    summary_rows: list[ExtractedSummaryRow] = Field(default_factory=list)
    # Audit context (ADR-004 §5.6): the exact reader + prompt that produced this extraction.
    model_id: str = ""
    prompt_hash: str = ""


@runtime_checkable
class VLMExtractor(Protocol):
    """Reads a rendered page into a :class:`RawExtraction`. The one seam Layer 2 programs against.

    Contract:
      * ``name`` identifies the concrete reader in logs/audit (e.g. ``"vlm:claude-sonnet-4-6"``).
      * ``available`` is False when the reader is not configured → the caller gates to NOT_EVALUATED.
      * ``extract`` returns transcription only; it MUST raise :class:`VLMUnavailable` when unconfigured
        and :class:`VLMExtractionError` on a real fault — never return a fabricated/partial pass.
      * ``handles_script`` lets the router ask whether this reader is a good fit for a script family.
    """

    name: str

    @property
    def available(self) -> bool: ...

    def handles_script(self, family: str) -> bool: ...

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction: ...
