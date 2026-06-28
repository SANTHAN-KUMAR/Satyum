"""Discrimination tests for the font / layout anomaly detector.

The claim under test: a line with ONE retyped/spliced word — off-baseline, odd x-height, or odd
stroke width — flags that word, while a typographically uniform line does NOT flag. This fails
against any constant: uniform must score 0, the spliced line must flag exactly one word; no constant
satisfies both. The per-word geometry uses the documented ``ctx.shared['ocr']`` schema (the same
shape ``words_from_tesseract`` produces), generated programmatically — never hand-tuned (§3.2 / §8).
"""

from __future__ import annotations

import numpy as np
import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.layout import (
    FontLayoutAnalyzer,
    analyze_layout,
    words_from_tesseract,
)

# --- synthetic OCR word geometry (the ctx.shared['ocr'] schema) ----------------------------------

def _word(text: str, left: int, top: int, height: int, conf: float = 0.9,
          line_num: int = 1, block_num: int = 1) -> dict:
    # width ~ proportional to glyph count, like a real OCR box; not used by the outlier features.
    return {"text": text, "left": left, "top": top, "width": len(text) * 16, "height": height,
            "conf": conf, "line_num": line_num, "block_num": block_num}


def _uniform_line() -> list[dict]:
    """Seven words on one line, all the same height with a shared baseline (+/- 1px OCR jitter)."""
    tokens = ["Opening", "Balance", "Credit", "Debit", "Closing", "Amount", "Branch"]
    words = []
    x = 20
    for i, tok in enumerate(tokens):
        top = 100 + (i % 2)            # sub-pixel-ish jitter a genuine line has
        words.append(_word(tok, x, top, height=30))
        x += len(tok) * 16 + 25
    return words


def _spliced_line(*, raise_baseline: bool = True, grow_height: bool = True) -> list[dict]:
    """The uniform line with ONE word retyped — a realistic cross-document paste: noticeably larger
    and shifted, the way a field copied from another document at a different scale appears.

    The magnitudes (height 30 -> 50, baseline raised ~20px) sit well past ordinary glyph-composition
    variance (ascender/descender boxes differ ~25-30%), which the detector's scale floors absorb."""
    words = _uniform_line()
    victim = words[4]  # 'Closing'
    if grow_height:
        victim["height"] = 50         # ~67% taller glyphs -> x-height outlier
    if raise_baseline:
        victim["top"] = 80            # baseline shifts well past composition variance
    return words


# --- pure-function discrimination ----------------------------------------------------------------

def test_uniform_line_is_not_flagged():
    result = analyze_layout(_uniform_line(), gray=None)
    assert result.evaluated is True
    assert result.flagged == [], result.reason


def test_spliced_word_is_flagged_and_localised():
    result = analyze_layout(_spliced_line(), gray=None)
    assert result.evaluated is True
    assert len(result.flagged) == 1, result.reason
    assert result.flagged[0].text == "Closing"
    assert result.flagged[0].reasons, "the flagged word must carry the feature(s) that broke"


def test_baseline_only_anomaly_is_caught():
    # Only the baseline is off (same height) — proves the baseline feature alone discriminates.
    result = analyze_layout(_spliced_line(raise_baseline=True, grow_height=False), gray=None)
    flagged = [g.text for g in result.flagged]
    assert "Closing" in flagged
    assert any("baseline" in r for g in result.flagged for r in g.reasons)


def test_xheight_only_anomaly_is_caught():
    result = analyze_layout(_spliced_line(raise_baseline=False, grow_height=True), gray=None)
    flagged = [g.text for g in result.flagged]
    assert "Closing" in flagged
    assert any("x-height" in r for g in result.flagged for r in g.reasons)


def test_short_tokens_and_thin_lines_are_not_assessed():
    # A line of mostly 1-2 char tokens has unreliable geometry -> honestly NOT evaluated.
    words = [_word("a", 20, 100, 30), _word("b", 60, 100, 30), _word("c", 100, 100, 30)]
    result = analyze_layout(words, gray=None)
    assert result.evaluated is False  # too few usable (>=3 char) words on any line


# --- stroke-width feature on a real image crop ---------------------------------------------------

def test_stroke_width_responds_to_font_weight():
    import cv2

    from forensics.layout import _stroke_width

    thin = np.full((40, 120), 255, np.uint8)
    cv2.putText(thin, "12345", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 1, cv2.LINE_AA)
    thick = np.full((40, 120), 255, np.uint8)
    cv2.putText(thick, "12345", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 3, cv2.LINE_AA)
    word = {"left": 0, "top": 0, "width": 120, "height": 40}
    # A heavier stroke must measure as a larger normalised stroke width — the real signal.
    assert _stroke_width(thick, word) > _stroke_width(thin, word) > 0.0


# --- analyzer wrapper / LayerSignal contract -----------------------------------------------------

def _ctx(words: list[dict]) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["ocr"] = words
    return ctx


def test_analyzer_discriminates_uniform_vs_spliced():
    az = FontLayoutAnalyzer()
    uniform = az.analyze(_ctx(_uniform_line()))
    spliced = az.analyze(_ctx(_spliced_line()))

    assert uniform.status == SignalStatus.VALID and uniform.suspicion == 0.0
    assert spliced.status == SignalStatus.VALID and spliced.suspicion > 0.0
    # the discriminating property:
    assert spliced.suspicion > uniform.suspicion
    # the spliced word must be localised for the underwriter
    assert spliced.evidence_regions
    assert any("Closing" in r.label for r in spliced.evidence_regions)


def test_analyzer_not_evaluated_without_ocr():
    az = FontLayoutAnalyzer()
    sig = az.analyze(AnalysisContext(session_id="t", intake_mode=Mode.FILE))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass


def test_constant_return_would_fail_discrimination():
    az = FontLayoutAnalyzer()
    uniform = az.analyze(_ctx(_uniform_line())).suspicion
    spliced = az.analyze(_ctx(_spliced_line())).suspicion
    # A constant return would make these equal; the real detector separates them.
    assert uniform != spliced


# --- honest non-coverage: a fully re-typeset (uniform) forgery is NOT caught here -----------------

def test_uniformly_retypeset_line_is_not_caught_by_layout():
    """If a forger re-typesets the WHOLE line consistently, there is no typographic outlier — this
    detector honestly does not catch it (that residual is the arithmetic / provenance job)."""
    tokens = ["Opening", "Balance", "Credit", "Debit", "Closing", "Amount", "Branch"]
    words, x = [], 20
    for tok in tokens:                       # every word same (different but uniform) typography
        words.append(_word(tok, x, 90, height=38))
        x += len(tok) * 16 + 25
    result = analyze_layout(words, gray=None)
    assert result.flagged == [], "a uniformly re-typeset line has no outlier; layout must not flag"


# --- end-to-end with real Tesseract OCR (skipped if tesseract / a TTF font is unavailable) --------

def _find_font(size: int):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
        "/usr/share/fonts/google-carlito-fonts/Carlito-Regular.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def test_end_to_end_real_ocr_uniform_line_not_flagged():
    pytesseract = pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw
    from pytesseract import Output

    font = _find_font(28)
    if font is None:
        pytest.skip("no TTF font available for rendering")
    try:
        pytesseract.get_tesseract_version()
    except (pytesseract.TesseractNotFoundError, OSError):
        pytest.skip("tesseract binary not installed")

    img = Image.new("L", (1100, 80), 255)
    draw = ImageDraw.Draw(img)
    x = 20
    for tok in ["Opening", "Balance", "Account", "Number", "Statement", "Period"]:
        draw.text((x, 28), tok, fill=0, font=font)
        x += int(draw.textlength(tok, font=font)) + 30
    gray = np.array(img)
    words = words_from_tesseract(pytesseract.image_to_data(img, output_type=Output.DICT))
    result = analyze_layout(words, gray)
    # A genuinely uniform machine-set line, through real OCR, must not raise a false typographic flag.
    assert all(not g.flagged for g in result.flagged) or result.evaluated is False
