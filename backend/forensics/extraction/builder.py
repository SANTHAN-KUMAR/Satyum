"""Assemble the verified :class:`ClaimGraph` from a raw extraction + the OCR cross-read (ADR-004 §5).

This is the trust junction. It takes the VLM's typed transcription and, for every cross-read-critical
number (Money, …), independently re-reads the cell from the pixels and records whether the reads agree.
A claim whose cross-read disagreed — or which never grounded to a box — is carried with
``cross_read_agree=False`` so its ``is_trusted`` gate fails and Layer 4 treats it as pending, never a
silent number. Free-text values that look like embedded instructions are dropped (§5.4); the VLM's
value type is never trusted — the builder assigns it from the predicate vocabulary.

Nothing here decides anything about the document. It produces claims; the deterministic layers judge.
"""

from __future__ import annotations

import io
import logging
import re
from decimal import Decimal

from app.claims import BBox, Claim, ClaimGraph, ClaimProvenance
from forensics.extraction.cross_read import CrossReadEnsemble
from forensics.extraction.interface import ExtractedValue, PageImage, RawExtraction
from forensics.extraction.schema import (
    DOC_TYPE_ENTITY_FIELDS,
    FIELD_VALUE_TYPE,
    TXN_CELL_VALUE_TYPE,
)
from forensics.ocr import parse_money
from ontology.loader import is_cross_read_critical, numeric_tolerance

logger = logging.getLogger(__name__)

# §5.4 — markers of an embedded prompt-injection attempt in a *free-text* value. A value that matches is
# dropped from the graph (defence in depth: the structured schema already denies the VLM any verdict, so
# such text can only ever be an inert claim — but it must never be propagated into the evidence console).
_INSTRUCTION_MARKERS = re.compile(
    r"""(?ix)
    ignore\s+(all\s+)?previous            # 'ignore previous instructions'
    | disregard\s+(the\s+)?(above|prior|previous)
    | \bsystem\s*:                        # role-injection
    | \bassistant\s*:
    | you\s+(are|must|should|have\s+been)
    | mark\s+(this\s+)?(as\s+)?verified
    | mark\s+(this\s+)?(as\s+)?approved
    | (set|return|output)\s+.{0,20}\b(verified|approved|genuine|valid)\b
    | override\s+(the\s+)?(instruction|rule|verdict)
    """
)


def _is_instruction_like(value: str) -> bool:
    return bool(_INSTRUCTION_MARKERS.search(value or ""))


def _pixel_bbox(norm: tuple[float, float, float, float] | None, width: int, height: int) -> BBox | None:
    if norm is None:
        return None
    x, y, w, h = norm
    return (x * width, y * height, w * width, h * height)


def _resolve_subject(doc_type: str, predicate: str) -> str:
    """Which entity instance a field predicate belongs to, given the document type.

    Resolves ``employer`` → ``salary_slip`` on a payslip vs ``income_proof`` on a Form-16, etc. A
    predicate not owned by any entity for this doc type falls back to a generic per-doc subject.
    """
    for entity, predicates in DOC_TYPE_ENTITY_FIELDS.get(doc_type, {}).items():
        if predicate in predicates:
            return entity
    return doc_type.lower()


def _canonical_number(value: str) -> tuple[Decimal | None, str]:
    """Parse a printed numeric string to ``Decimal`` + canonical text, or ``(None, raw)`` if not numeric."""
    dec = parse_money(value)
    if dec is None:
        return None, value
    return dec, str(dec)


class ClaimGraphBuilder:
    """Builds a cross-read-verified claim graph for one document page."""

    def __init__(self, ensemble: CrossReadEnsemble, *, arithmetic_abs_tolerance: float) -> None:
        self._ensemble = ensemble
        self._tol = arithmetic_abs_tolerance

    def build(self, raw: RawExtraction, page: PageImage, *, doc_id: str, source: str) -> ClaimGraph:
        """Single-page build (the camera path and any one-page document)."""
        graph = ClaimGraph(doc_id=doc_id, doc_type=raw.doc_type, primary_language=raw.primary_language)
        self._add_page(graph, raw, page, doc_id=doc_id, source=source, seq_offset=0, seen_fields=set())
        return graph

    def build_multi(
        self, pages: list[tuple[RawExtraction, PageImage]], *, doc_id: str, source: str
    ) -> ClaimGraph:
        """Merge a multi-page document into ONE claim graph (ADR-004 §3 — a statement spans pages).

        A real bank statement carries opening/closing on the summary page and the transaction rows over
        several continuation pages; the running-balance chain and the net reconciliation are only correct
        over the COMPLETE set. We extract each page (each cell cross-read against its own page's exact
        text layer), renumber transactions continuously so the chain is unbroken across the page break,
        and keep the first occurrence of each scalar field (opening/closing appear once, on page 1).
        """
        doc_type = next((r.doc_type for r, _ in pages if r.doc_type and r.doc_type != "OTHER"), "OTHER")
        primary_language = pages[0][0].primary_language if pages else "en"
        graph = ClaimGraph(doc_id=doc_id, doc_type=doc_type, primary_language=primary_language)
        seq_offset = 0
        seen_fields: set[tuple[str, str]] = set()
        for raw, page in pages:
            seq_offset = self._add_page(
                graph, raw, page, doc_id=doc_id, source=source,
                seq_offset=seq_offset, seen_fields=seen_fields,
            )
        return graph

    def _add_page(
        self,
        graph: ClaimGraph,
        raw: RawExtraction,
        page: PageImage,
        *,
        doc_id: str,
        source: str,
        seq_offset: int,
        seen_fields: set[tuple[str, str]],
    ) -> int:
        """Add one page's claims to ``graph``; return the next transaction-seq offset.

        ``seq_offset`` renumbers this page's transactions so they continue the previous page's sequence
        (so the running-balance chain is unbroken across pages). ``seen_fields`` deduplicates scalar
        fields/summary rows that the model might repeat in a page header (keep the first occurrence).

        The reader's own ``txn.seq`` is untrusted input (CLAUDE.md §3.1/§5.4): used only to sort this
        page's rows into document order (best-effort — it is still the model's best signal of "which
        came first"), never to size the next page's offset. A page's global index always advances by
        exactly the number of rows this page actually produced, so a reader whose per-page numbering is
        non-zero-based, gapped, or duplicated cannot drop rows or misalign every later page.
        """
        page_img = self._decode(page)

        for f in raw.fields:
            value_type = FIELD_VALUE_TYPE.get(f.predicate)
            if value_type is None:  # unknown predicate slipped through — never trust it (§5.4)
                continue
            subject = _resolve_subject(raw.doc_type or graph.doc_type or "OTHER", f.predicate)
            if (subject, f.predicate) in seen_fields:
                continue  # a repeated header field on a later page — keep the first
            seen_fields.add((subject, f.predicate))
            claim = self._make_claim(
                subject=subject, predicate=f.predicate, value=f.value, value_type=value_type,
                norm_bbox=f.bbox, confidence=f.confidence, page=page, page_img=page_img,
                source=source, doc_id=doc_id, index=None,
            )
            if claim is not None:
                graph.add(claim)

        ordered_txns = sorted(raw.transactions, key=lambda t: t.seq)
        for local_i, txn in enumerate(ordered_txns):
            seq = seq_offset + local_i
            for cell_name, value_type in TXN_CELL_VALUE_TYPE.items():
                cell: ExtractedValue | None = getattr(txn, cell_name)
                if cell is None:
                    continue
                claim = self._make_claim(
                    subject=f"transaction_{seq}", predicate=cell_name, value=cell.value,
                    value_type=value_type, norm_bbox=cell.bbox, confidence=cell.confidence,
                    page=page, page_img=page_img, source=source, doc_id=doc_id, index=seq,
                )
                if claim is not None:
                    graph.add(claim)

        for row in raw.summary_rows:
            if ("summary", row.kind) in seen_fields:
                continue
            seen_fields.add(("summary", row.kind))
            claim = self._make_claim(
                subject="summary", predicate=row.kind, value=row.amount.value, value_type="Money",
                norm_bbox=row.amount.bbox, confidence=row.amount.confidence, page=page,
                page_img=page_img, source=source, doc_id=doc_id, index=None,
            )
            if claim is not None:
                graph.add(claim)

        return seq_offset + len(ordered_txns)

    # --- internals --------------------------------------------------------------------------------

    @staticmethod
    def _decode(page: PageImage):
        """Decode the rendered PNG once for cropping; ``None`` if Pillow is unavailable (cross-read off)."""
        try:
            from PIL import Image

            return Image.open(io.BytesIO(page.png_bytes)).convert("RGB")
        except Exception as exc:  # noqa: BLE001 — no decode ⇒ no cross-read ⇒ numerics stay untrusted
            logger.info("builder: could not decode page image for cross-read: %r", exc)
            return None

    def _make_claim(
        self,
        *,
        subject: str,
        predicate: str,
        value: str,
        value_type: str,
        norm_bbox: tuple[float, float, float, float] | None,
        confidence: float,
        page: PageImage,
        page_img,
        source: str,
        doc_id: str,
        index: int | None,
    ) -> Claim | None:
        # An absent printed value is not a claim — a reader may emit an empty cell for a row that has
        # only a debit or only a credit. Skip it rather than carry a blank, untrusted claim (noise).
        if not value.strip():
            return None
        cross_read_required = is_cross_read_critical(value_type)
        pixel_bbox = _pixel_bbox(norm_bbox, page.width, page.height)
        prov = ClaimProvenance(
            doc_id=doc_id, page=page.page_index, bbox=pixel_bbox, confidence=confidence, source=source
        )

        if cross_read_required:
            canonical_dec, canonical_str = _canonical_number(value)
            value = canonical_str
            have_textlayer = bool(page.text_words)
            if canonical_dec is None:
                # The VLM reported a non-numeric value for a numeric field — never trust it.
                prov.cross_read_agree = False
                prov.cross_read_detail = "VLM value is not a parseable number"
            elif page_img is None and not have_textlayer:
                # No independent decode available at all (PIL decode failed AND no PDF text layer).
                prov.cross_read_agree = False
                prov.cross_read_detail = "no independent decode available — number could not be re-read"
            else:
                tol = numeric_tolerance(value_type, arithmetic_abs_tolerance=self._tol)
                outcome = self._ensemble.verify(
                    page_img, norm_bbox, canonical_dec, tol, text_words=page.text_words
                )
                prov.cross_read_agree = outcome.agree
                prov.cross_read_detail = outcome.detail
                prov.corroborating_read = (
                    "; ".join(f"{name}={vals}" for name, vals in outcome.reads.items()) or None
                )
        else:
            # Free-text / validated string: scrub an embedded instruction; never trust the VLM's type.
            if _is_instruction_like(value):
                logger.info("builder: dropped instruction-like value for %s.%s", subject, predicate)
                return None

        return Claim(
            subject=subject,
            predicate=predicate,
            value=value,
            value_type=value_type,
            index=index,
            cross_read_required=cross_read_required,
            provenance=prov,
        )
