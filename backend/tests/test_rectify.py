"""Discrimination tests for the Tier-3 rectify + capture-quality analyzer.

Proves the analyzer SEPARATES a usable capture from a poor one and fails CLOSED on poor capture
(BUILD-MANIFEST guard: "poor capture must fail-closed to REVIEW, not pass"). Every test fails
against a constant return: a sharp page must be VALID while a blurred page must be NOT_EVALUATED,
and the focus measure must move with sharpness — no constant satisfies both.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from capture.rectify import (
    RectifyQualityAnalyzer,
    find_document_quad,
    focus_measure,
    rectify,
)
from tests.capture_fixtures import page_on_background


def _camera_ctx(frame) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.append(frame)
    return ctx


# --- the core discriminative claim: focus measure tracks sharpness ---------------------------

def test_focus_measure_separates_sharp_from_blurred():
    sharp = cv2.cvtColor(page_on_background(blur=False), cv2.COLOR_BGR2GRAY)
    blurred = cv2.cvtColor(page_on_background(blur=True), cv2.COLOR_BGR2GRAY)
    # The variance-of-Laplacian must be much higher for the in-focus page.
    assert focus_measure(sharp) > 10 * focus_measure(blurred)


def test_quad_detected_on_page_with_visible_border():
    quad = find_document_quad(page_on_background(blur=False))
    assert quad is not None
    assert quad.shape == (4, 2)


def test_rectify_produces_fronto_parallel_crop():
    page = page_on_background(blur=False)
    quad = find_document_quad(page)
    assert quad is not None
    crop = rectify(page, quad)
    assert crop.ndim == 3 and crop.shape[2] == 3
    assert crop.shape[0] > 0 and crop.shape[1] > 0


# --- analyzer contract: sharp PASSES, blurred FAILS CLOSED -----------------------------------

def test_sharp_capture_is_valid_and_publishes_rectified():
    az = RectifyQualityAnalyzer()
    ctx = _camera_ctx(page_on_background(blur=False))
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion < 0.5
    # foundation contract: the rectified crop is published for downstream analyzers
    assert isinstance(ctx.shared.get("rectified"), np.ndarray)
    assert ctx.shared["rectified"].ndim == 3


def test_blurred_capture_fails_closed_to_not_evaluated():
    az = RectifyQualityAnalyzer()
    ctx = _camera_ctx(page_on_background(blur=True))
    sig = az.analyze(ctx)
    # poor capture must NOT be a pass — it is excluded from the score (REVIEW downstream)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None
    assert "focus" in sig.reason.lower()
    # and it must NOT have published a (bad) rectified crop for others to trust
    assert "rectified" not in ctx.shared


def test_discrimination_sharp_vs_blurred_is_not_a_constant():
    """The §3.2 litmus: a constant return cannot make sharp VALID and blurred NOT_EVALUATED."""
    az = RectifyQualityAnalyzer()
    sharp = az.analyze(_camera_ctx(page_on_background(blur=False)))
    blurred = az.analyze(_camera_ctx(page_on_background(blur=True)))
    assert sharp.status == SignalStatus.VALID
    assert blurred.status == SignalStatus.NOT_EVALUATED
    assert sharp.status != blurred.status


def test_no_frames_is_not_evaluated_not_error():
    az = RectifyQualityAnalyzer()
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    assert az.applicable(ctx) is False
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_malformed_frame_is_error_not_pass():
    """Fail-closed: a garbage frame becomes ERROR, never a silent VALID pass."""
    az = RectifyQualityAnalyzer()
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.append(np.zeros((10, 10), dtype=np.uint8))  # 2-D, not BGR
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.ERROR


def test_no_document_in_frame_fails_closed():
    """A frame with no detectable document quad fails closed, never a pass."""
    az = RectifyQualityAnalyzer()
    blank = np.full((300, 300, 3), 128, np.uint8)  # uniform — no quad
    sig = az.analyze(_camera_ctx(blank))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_producing_mode_is_camera_not_file():
    """Mode-tagging invariant: this signal can never claim to be a FILE signal."""
    az = RectifyQualityAnalyzer()
    sig = az.analyze(_camera_ctx(page_on_background(blur=False)))
    assert sig.producing_mode == Mode.CAMERA


@pytest.mark.parametrize("blur", [False, True])
def test_analyze_never_raises_on_ordinary_input(blur):
    az = RectifyQualityAnalyzer()
    sig = az.analyze(_camera_ctx(page_on_background(blur=blur)))
    assert sig.status in (SignalStatus.VALID, SignalStatus.NOT_EVALUATED)
