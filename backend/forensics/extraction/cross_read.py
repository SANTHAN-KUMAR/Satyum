"""The numeric cross-read consensus — the control that makes a generative reader safe (ADR-004 §5.2).

A VLM is trained to produce *plausible* output: given a tampered figure it may silently "correct" it
into a value that reconciles, laundering a forgery into a clean-looking statement. The defence is not
to trust the model's number at all — it is to **independently re-read every cross-read-critical figure
from the actual pixels** and require agreement. A tamper one reader smooths, an independent reader
reads literally → they disagree → the claim is held ``NOT_EVALUATED`` (pending), never a silent pick.

We deliberately do **not** rely on a single OCR pass. The cross-read is an *ensemble* of independent
deterministic decodings (CLAUDE.md §4, program to a ``NumericReader`` interface): different Tesseract
page-segmentation modes plus a digit-restricted pass, each reading the same cell crop, with a
**consensus** rule — and the interface accepts additional engines (PaddleOCR / a self-hosted Indic OCR)
as drop-in readers for vernacular numerals, exactly as the VLM layer is swappable. The decision rule is
fail-closed: a reader that disagrees, or a cell no reader can read, blocks trust rather than granting
it. The number's authority comes from grounded, independently-verified transcription — not the model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from forensics.ocr import parse_money

logger = logging.getLogger(__name__)

# A crop is padded slightly so glyphs at the box edge are not clipped, but not so much that a neighbour
# cell's digits are pulled in. Fraction of the box's own size + a pixel floor. DEFAULT — a geometric
# tolerance, not a detection threshold; widen only if real boxes prove to clip.
_CROP_PAD_FRAC = 0.08
_CROP_PAD_MIN_PX = 3
# Tesseract reads small text poorly; upscale a short crop to a workable height before OCR (standard
# practice, improves digit recall without changing what is printed).
_MIN_CROP_HEIGHT_PX = 40

# Number tokens: Indian/Western grouped digits with optional decimals, optional sign. Used to find
# every numeric substring a reader saw in a crop (so we can ask "did this reader see the claimed value?").
_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|-?\d+(?:\.\d{1,2})?")


def numbers_in(text: str) -> list[Decimal]:
    """Every distinct numeric value a reader transcribed from a crop (robust to digit fragmentation).

    Tesseract routinely splits one printed figure into space-separated fragments (``15, 000. 00``); we
    therefore consider the whole-cell parse, each whitespace token, and each regex hit, returning the
    union. Permissive on *what was seen* so consensus is asked fairly — never invents a value.
    """
    seen: set[Decimal] = set()
    whole = parse_money(text)
    if whole is not None:
        seen.add(whole)
    for token in text.split():
        v = parse_money(token)
        if v is not None:
            seen.add(v)
    for m in _NUM_RE.finditer(text):
        v = parse_money(m.group(0))
        if v is not None:
            seen.add(v)
    return list(seen)


@runtime_checkable
class NumericReader(Protocol):
    """One independent deterministic decoding of a cell crop into the numbers it contains."""

    name: str

    def read_numbers(self, crop: Any) -> list[Decimal]: ...


class TesseractNumericReader(NumericReader):
    """A Tesseract decoding of a crop under one specific page-segmentation/character configuration.

    Two instances with different configs (a general single-line read and a digit-whitelisted read) form
    an ensemble whose disagreement is itself signal. Lazy ``pytesseract`` import; a reader that fails on
    a crop contributes *nothing* (an empty read), never a fabricated number — so a broken engine cannot
    manufacture a false agreement (fail-closed).
    """

    def __init__(self, *, name: str, config: str) -> None:
        self.name = name
        self._config = config

    def read_numbers(self, crop: Any) -> list[Decimal]:
        try:
            import pytesseract
        except ImportError:
            logger.warning("cross-read: pytesseract unavailable; %s read skipped", self.name)
            return []
        try:
            text = pytesseract.image_to_string(crop, config=self._config)
        except Exception as exc:  # noqa: BLE001 — a reader failure is an empty read, never a fault
            logger.info("cross-read: %s failed on crop: %r", self.name, exc)
            return []
        return numbers_in(text or "")


@dataclass(frozen=True)
class CrossReadOutcome:
    """The ensemble's verdict on one numeric claim, with the per-reader reads for the audit/console."""

    agree: bool
    detail: str
    reads: dict[str, list[str]] = field(default_factory=dict)


def _crop_for(page_img: Any, norm_bbox: tuple[float, float, float, float]) -> Any | None:
    """Crop the page (a PIL image) to a normalized box, padded and upscaled for OCR. ``None`` if empty."""
    width, height = page_img.size
    x, y, w, h = norm_bbox
    px = x * width
    py = y * height
    pw = w * width
    ph = h * height
    pad_x = max(pw * _CROP_PAD_FRAC, _CROP_PAD_MIN_PX)
    pad_y = max(ph * _CROP_PAD_FRAC, _CROP_PAD_MIN_PX)
    left = max(0, int(px - pad_x))
    top = max(0, int(py - pad_y))
    right = min(width, int(px + pw + pad_x))
    bottom = min(height, int(py + ph + pad_y))
    if right <= left or bottom <= top:
        return None
    crop = page_img.crop((left, top, right, bottom))
    crop_h = bottom - top
    if crop_h < _MIN_CROP_HEIGHT_PX:
        scale = _MIN_CROP_HEIGHT_PX / float(crop_h)
        from PIL import Image

        crop = crop.resize((max(1, int(crop.width * scale)), _MIN_CROP_HEIGHT_PX), Image.LANCZOS)
    return crop


class CrossReadEnsemble:
    """Re-reads a claimed numeric value from the pixels with several readers and applies consensus."""

    def __init__(self, readers: list[NumericReader]) -> None:
        if not readers:
            raise ValueError("CrossReadEnsemble needs at least one reader")
        self._readers = readers

    @property
    def reader_names(self) -> list[str]:
        return [r.name for r in self._readers]

    def verify(
        self,
        page_img: Any,
        norm_bbox: tuple[float, float, float, float] | None,
        claimed: Decimal,
        tolerance: float,
    ) -> CrossReadOutcome:
        """Decide whether the independent readers confirm ``claimed`` at ``norm_bbox``.

        Consensus rule (fail-closed):
          * **AGREE** — at least one reader read the claimed value (within ``tolerance``) AND every
            reader that read *any* number at the cell saw the claimed value. No independent reader
            contradicts it.
          * **DISAGREE** — some reader read a number at the cell but none of its reads matched the
            claim: an independent reader literally sees a different figure (the laundering catch).
          * **UNREAD** — no reader could read a number there: we cannot confirm, so we do not.
        Only AGREE sets ``agree=True``; DISAGREE and UNREAD both withhold trust (→ NOT_EVALUATED).
        """
        if norm_bbox is None:
            return CrossReadOutcome(False, "claim has no bounding box to re-read (ungrounded)")
        crop = _crop_for(page_img, norm_bbox)
        if crop is None:
            return CrossReadOutcome(False, "bounding box does not map to a readable region")

        tol = Decimal(str(tolerance))
        reads: dict[str, list[str]] = {}
        readers_that_read = 0
        readers_matching = 0
        readers_contradicting = 0
        for reader in self._readers:
            nums = reader.read_numbers(crop)
            reads[reader.name] = [str(n) for n in nums]
            if not nums:
                continue
            readers_that_read += 1
            if any(abs(n - claimed) <= tol for n in nums):
                readers_matching += 1
            else:
                readers_contradicting += 1

        if readers_that_read == 0:
            return CrossReadOutcome(False, "no OCR reader could read a number at this cell", reads)
        if readers_matching >= 1 and readers_contradicting == 0:
            return CrossReadOutcome(
                True,
                f"{readers_matching}/{len(self._readers)} reader(s) independently confirmed {claimed}",
                reads,
            )
        return CrossReadOutcome(
            False,
            f"OCR cross-read disagrees with the reader: claimed {claimed}, "
            f"{readers_contradicting} independent read(s) saw a different figure",
            reads,
        )


def default_ensemble() -> CrossReadEnsemble:
    """The always-on cross-read: two independent Tesseract decodings of each numeric cell.

    ``--psm 7`` treats the crop as one text line (the common case for a statement cell); the second
    pass restricts the alphabet to digits/separators so a smudged letter cannot masquerade as a digit.
    They fail differently, so requiring their consensus is materially stronger than any single pass. The
    ensemble takes more readers (e.g. a PaddleOCR or self-hosted Indic reader for vernacular numerals)
    with no change here — that is the point of the ``NumericReader`` seam.
    """
    return CrossReadEnsemble(
        [
            TesseractNumericReader(name="tesseract-line", config="--oem 1 --psm 7"),
            TesseractNumericReader(
                name="tesseract-digits",
                config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.,-",
            ),
        ]
    )
