"""Language-aware routing of the extraction across multiple VLM backends (ADR-004 §7; India-first).

A frontier English-centric model is not automatically the best reader for a Devanagari, Tamil, or
Kannada document. Rather than lock one model in, the extractor is chosen by the document's script:

  * a deterministic :func:`detect_script` reads the page's script from its embedded text layer when
    present (free, no OCR) — and the reader also reports the language it saw;
  * :class:`LanguageRoutedExtractor` sends an Indic-script document to a registered Indic specialist
    (e.g. an in-perimeter Sarvam-class model — sovereign, 22-language) when one is configured, and
    otherwise to the capable default reader (Claude/Gemini), **escalating** to the specialist when the
    default's own confidence on a vernacular page is low.

This is the seam that makes "aware of Indian diversity" a real engineering property: adding the Indic
specialist is registering one more :class:`VLMExtractor`, not a rewrite. With only the default
configured the router is a transparent pass-through (one call, no escalation).
"""

from __future__ import annotations

import logging

from forensics.extraction.interface import PageImage, RawExtraction, VLMExtractor

logger = logging.getLogger(__name__)

# Unicode letter blocks per Indian script. A document is "indic" when these letters dominate the
# letters on the page. (Numbers are usually Western digits even in vernacular docs — see cross_read.)
_INDIC_BLOCKS: dict[str, tuple[int, int]] = {
    "Devanagari": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Gujarati": (0x0A80, 0x0AFF),
    "Oriya": (0x0B00, 0x0B7F),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
}

# ISO-639-1 / common codes a reader may report for an Indic language (maps to the "indic" family).
_INDIC_LANG_CODES = frozenset(
    {"hi", "bn", "gu", "kn", "ml", "mr", "ta", "te", "pa", "or", "as", "sa", "ne", "sd", "ks", "kok"}
)

FAMILY_LATIN = "latin"
FAMILY_INDIC = "indic"
FAMILY_UNKNOWN = "unknown"


def _script_of(codepoint: int) -> str | None:
    """The Indic script name for a codepoint, ``"Latin"`` for Latin letters, else ``None``."""
    if (0x41 <= codepoint <= 0x5A) or (0x61 <= codepoint <= 0x7A) or (0xC0 <= codepoint <= 0x24F):
        return "Latin"
    for name, (lo, hi) in _INDIC_BLOCKS.items():
        if lo <= codepoint <= hi:
            return name
    return None


def detect_script(text: str) -> tuple[str, str]:
    """Return ``(family, dominant_script)`` for ``text``: ``family`` ∈ {latin, indic, unknown}.

    Pure, deterministic Unicode-block analysis over the letters present — directly unit-tested. A page
    with more Indic letters than Latin letters is ``indic`` (named by its dominant Indic script); a page
    with letters but no clear Indic majority is ``latin``; a page with no letters is ``unknown``.
    """
    counts: dict[str, int] = {}
    for ch in text:
        script = _script_of(ord(ch))
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return FAMILY_UNKNOWN, ""
    indic_total = sum(n for s, n in counts.items() if s != "Latin")
    latin_total = counts.get("Latin", 0)
    if indic_total > latin_total:
        dominant = max((s for s in counts if s != "Latin"), key=lambda s: counts[s])
        return FAMILY_INDIC, dominant
    return FAMILY_LATIN, "Latin"


def family_for_language(code: str) -> str:
    """Map a reader-reported language code (``hi``, ``ta``, ``en`` …) to a script family."""
    base = (code or "").strip().lower().split("-")[0]
    if base in _INDIC_LANG_CODES:
        return FAMILY_INDIC
    if base == "en":
        return FAMILY_LATIN
    return FAMILY_UNKNOWN


def _mean_confidence(result: RawExtraction) -> float:
    """Mean confidence across all located values — the signal the router escalates on."""
    confs = [f.confidence for f in result.fields]
    for txn in result.transactions:
        for cell in (
            txn.posted_on,
            txn.value_date,
            txn.description,
            txn.debit,
            txn.credit,
            txn.running_balance,
        ):
            if cell is not None:
                confs.append(cell.confidence)
    for row in result.summary_rows:
        confs.append(row.amount.confidence)
    return sum(confs) / len(confs) if confs else 0.0


class LanguageRoutedExtractor(VLMExtractor):
    """Routes each page to the best-fit reader by script, escalating low-confidence vernacular reads."""

    def __init__(
        self,
        *,
        default: VLMExtractor,
        specialists: dict[str, VLMExtractor] | None = None,
        escalate_below_confidence: float = 0.60,
    ) -> None:
        self._default = default
        self._specialists = specialists or {}
        self._escalate = escalate_below_confidence

    @property
    def name(self) -> str:
        spec = ",".join(f"{fam}->{ex.name}" for fam, ex in self._specialists.items())
        return f"router[{self._default.name}{(' | ' + spec) if spec else ''}]"

    @property
    def available(self) -> bool:
        return self._default.available

    def handles_script(self, family: str) -> bool:
        return True

    def _specialist_for(self, family: str) -> VLMExtractor | None:
        ex = self._specialists.get(family)
        if ex is not None and ex.available and ex.handles_script(family):
            return ex
        return None

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        # 1) Free, deterministic pre-route from the PDF text layer when present.
        if page.text_layer.strip():
            family, dominant = detect_script(page.text_layer)
            if family == FAMILY_INDIC:
                specialist = self._specialist_for(FAMILY_INDIC)
                if specialist is not None:
                    logger.info("routing: %s script → Indic specialist %s", dominant, specialist.name)
                    return specialist.extract(page, doc_type_hint=doc_type_hint)

        # 2) Default read.
        result = self._default.extract(page, doc_type_hint=doc_type_hint)

        # 3) Confidence-gated escalation: a vernacular page the default read weakly goes to the
        #    specialist if one is configured (the "produce a confidence and decide which to use" path).
        if family_for_language(result.primary_language) == FAMILY_INDIC:
            specialist = self._specialist_for(FAMILY_INDIC)
            if specialist is not None and specialist.name != self._default.name:
                if _mean_confidence(result) < self._escalate:
                    logger.info(
                        "routing: default read %s at low confidence → escalating to %s",
                        result.primary_language,
                        specialist.name,
                    )
                    return specialist.extract(page, doc_type_hint=doc_type_hint)
        return result
