"""Discrimination tests for the copy-move (region-clone) detector.

The claim under test: a pasted duplicate region is flagged with BOTH bounding boxes, while a clean
document and a *legitimately repetitive* document (a ruled grid / a row of identical glyphs) are NOT
flagged. These would FAIL against any constant return — a clone must raise suspicion while clean and
grid keep it at 0; no constant satisfies all three. Fixtures are generated programmatically with
OpenCV (CLAUDE.md §3.2 / §8), never hand-tuned until a test passes.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.copy_move import (
    CopyMoveAnalyzer,
    detect_copy_move,
)


# --- programmatic fixtures (no external assets) --------------------------------------------------

def _statement_like(seed: int = 11) -> np.ndarray:
    """A document with VARIED text tokens — like a real statement, not one glyph repeated.

    Varied content is the realistic case: a genuine statement has many distinct words, so the only
    way to get a coherent equal-offset match cluster is an actual pasted region.
    """
    rng = np.random.default_rng(seed)
    img = np.full((400, 600), 255, np.uint8)
    tokens = ["Salary", "12,450.00", "HDFC", "Rent", "9876", "Bal", "Acct", "2025",
              "Credit", "Debit", "NEFT", "UPI", "Ref", "554", "Bharat", "Loan", "EMI", "3,200"]
    for i in range(90):
        x = int(rng.integers(20, 520))
        y = int(rng.integers(25, 370))
        cv2.putText(img, tokens[i % len(tokens)] + str(i % 7), (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, float(rng.uniform(0.45, 0.75)), 0, 1, cv2.LINE_AA)
    return img


def _clone_patch(base: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Return a copy of ``base`` with a rectangular region copied and pasted elsewhere.

    The pasted region carries identical texture to its source, which is exactly what copy-move
    forensics must detect. Returns the forged image and the (x, y, w, h) of the paste destination.
    """
    forged = base.copy()
    sy, sx, h, w = 40, 60, 110, 130          # source region (y, x, height, width)
    dy, dx = 230, 380                        # paste destination
    forged[dy:dy + h, dx:dx + w] = base[sy:sy + h, sx:sx + w]
    return forged, (dx, dy, w, h)


def _grid(spacing: int = 30) -> np.ndarray:
    """Legitimately repetitive structure: a ruled grid. Must NOT be flagged as a clone."""
    img = np.full((400, 600), 255, np.uint8)
    for gx in range(0, 600, spacing):
        cv2.line(img, (gx, 0), (gx, 400), 0, 1)
    for gy in range(0, 400, spacing):
        cv2.line(img, (0, gy), (600, gy), 0, 1)
    return img


def _repeated_logo(count: int = 12) -> np.ndarray:
    """Legitimately repeated identical glyphs/logos scattered across the page (FP control)."""
    img = np.full((400, 600), 255, np.uint8)
    rng = np.random.default_rng(3)
    for _ in range(count):
        x = int(rng.integers(30, 520))
        y = int(rng.integers(40, 360))
        cv2.circle(img, (x, y), 14, 0, 2)
        cv2.putText(img, "LOGO", (x - 12, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 0, 1, cv2.LINE_AA)
    return img


# --- pure-detector discrimination ----------------------------------------------------------------

def test_clean_document_is_not_flagged():
    result = detect_copy_move(_statement_like())
    assert result.evaluated is True
    assert result.duplicated is False, result.reason


def test_pasted_clone_is_detected_and_localised():
    base = _statement_like()
    forged, (dx, dy, w, h) = _clone_patch(base)
    result = detect_copy_move(forged)

    assert result.evaluated is True
    assert result.duplicated is True, result.reason
    assert result.source_bbox is not None and result.paste_bbox is not None

    # The two flagged regions must localise the actual clone: one bbox near the source, one near the
    # paste destination. We check the paste bbox overlaps the destination we wrote.
    boxes = [result.source_bbox, result.paste_bbox]
    paste_hit = any(
        abs(bx - dx) < w and abs(by - dy) < h for (bx, by, bw, bh) in boxes
    )
    assert paste_hit, f"neither flagged region localises the paste at ({dx},{dy}): {boxes}"


def test_ruled_grid_is_not_a_false_clone():
    # Legitimately repeated structure must stay quiet — the repetition guard's whole purpose.
    result = detect_copy_move(_grid())
    assert result.duplicated is False, result.reason


def test_repeated_logos_are_not_a_false_clone():
    result = detect_copy_move(_repeated_logo())
    assert result.duplicated is False, result.reason


# --- analyzer wrapper / LayerSignal contract -----------------------------------------------------

def _ctx(image: np.ndarray) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["rectified"] = image
    return ctx


def test_analyzer_discriminates_clone_vs_clean():
    az = CopyMoveAnalyzer()
    clean = az.analyze(_ctx(_statement_like()))
    forged_img, _ = _clone_patch(_statement_like())
    forged = az.analyze(_ctx(forged_img))

    assert clean.status == SignalStatus.VALID and clean.suspicion == 0.0
    assert forged.status == SignalStatus.VALID and forged.suspicion > 0.5
    # the discriminating property — the whole point of the detector:
    assert forged.suspicion > clean.suspicion
    # a caught clone must produce BOTH evidence regions for the underwriter
    assert len(forged.evidence_regions) == 2
    assert {r.label for r in forged.evidence_regions} == {
        "copy-move source region", "copy-move pasted region"
    }


def test_analyzer_not_evaluated_without_image():
    az = CopyMoveAnalyzer()
    sig = az.analyze(AnalysisContext(session_id="t", intake_mode=Mode.FILE))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass


def test_grid_analyzer_does_not_false_flag():
    az = CopyMoveAnalyzer()
    sig = az.analyze(_ctx(_grid()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.evidence_regions == []


# --- the §3.2 constant-return litmus, local to this detector -------------------------------------

class _ConstantCopyMove:
    """A fake that always reports a clone — must FAIL the discrimination assertion below."""

    def analyze_susp(self, ctx):  # noqa: ANN001
        return 0.9


def test_constant_return_would_fail_discrimination():
    az = CopyMoveAnalyzer()
    clean = az.analyze(_ctx(_statement_like())).suspicion
    forged_img, _ = _clone_patch(_statement_like())
    forged = az.analyze(_ctx(forged_img)).suspicion
    # If the analyzer returned a constant, clean == forged and this separation would vanish.
    assert clean != forged
    constant = _ConstantCopyMove()
    assert constant.analyze_susp(_ctx(_statement_like())) == constant.analyze_susp(_ctx(forged_img))


@pytest.mark.parametrize("seed", [11, 23, 47])
def test_clone_detected_across_seeds(seed):
    base = _statement_like(seed)
    forged, _ = _clone_patch(base)
    assert detect_copy_move(base).duplicated is False
    assert detect_copy_move(forged).duplicated is True
