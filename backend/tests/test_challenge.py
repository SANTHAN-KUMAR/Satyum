"""Discrimination tests for the CENTERPIECE active 3D challenge-response analyzer.

The BUILD-MANIFEST must-pass guard: "photo-of-screen replay FAILS; live tilt matching the command
PASSES; wrong-direction motion FAILS." Each test fails against a constant return — no fixed
suspicion can make a matching tilt low-suspicion while a static replay, a wrong-axis tilt, and an
inconsistent double-perspective are all high-suspicion.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, Mode, SignalStatus
from capture.challenge import (
    ActiveChallengeAnalyzer,
    _center_crop_mask,
    _document_seed_mask,
    angular_jerk_cv,
    homography_consistency,
    recover_axis_angles,
    track_corners,
)
from tests.capture_fixtures import (
    challenge_sequence,
    double_perspective_sequence,
    small_document_over_busy_static_background,
    static_challenge_sequence,
)


def _ctx(frames, challenge) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.extend(frames)
    if challenge is not None:
        ctx.shared["challenge"] = challenge
    return ctx


def _cmd(axis: str, deg: float) -> dict:
    return {"axis": axis, "magnitude_deg": deg, "deadline_ms": 4000}


def _susp(signal) -> float:
    """Assert a VALID signal carries a real suspicion and return it (type-safe comparisons)."""
    assert signal.status == SignalStatus.VALID
    assert signal.suspicion is not None
    return signal.suspicion


# ============================================================================================
#  Core: the recovered transform matches the commanded one
# ============================================================================================

def test_tracking_and_homography_recover_commanded_tilt():
    """The realised tilt recovered from tracked corners matches the synthesised command (~15 deg)."""
    frames = challenge_sequence("x", 15.0)
    tracked = track_corners(frames)
    assert tracked is not None
    start, end = tracked
    n = frames[0].shape[0]
    k = np.array([[1.2 * n, 0, n / 2], [0, 1.2 * n, n / 2], [0, 0, 1]], dtype=np.float64)
    matrix, inlier_ratio, residual = homography_consistency(start, end)
    assert matrix is not None
    angles = recover_axis_angles(matrix, k)
    # commanded axis recovered near 15 deg; the other axis near 0
    assert abs(angles["x"] - 15.0) < settings.challenge_homography_tol_deg
    assert angles["y"] < settings.challenge_homography_tol_deg
    # single consistent plane: high inliers, low residual
    assert inlier_ratio > 0.6 and residual < 6.0


# ============================================================================================
#  PASS: live tilt matching the command
# ============================================================================================

def test_matching_tilt_passes_low_suspicion():
    az = ActiveChallengeAnalyzer()
    frames = challenge_sequence("x", 15.0)
    sig = az.analyze(_ctx(frames, _cmd("x", 15.0)))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion <= 0.1
    assert sig.measurements["axis_match"] is True
    assert sig.measurements["magnitude_match"] is True
    assert sig.measurements["single_homography_consistent"] is True


# ============================================================================================
#  FAIL: static replay (photo / frozen video) cannot satisfy the command
# ============================================================================================

def test_static_replay_fails_high_suspicion():
    az = ActiveChallengeAnalyzer()
    frames = static_challenge_sequence()
    sig = az.analyze(_ctx(frames, _cmd("x", 15.0)))
    # no commanded motion realised -> challenge unmet -> high suspicion
    assert _susp(sig) >= 0.7
    assert sig.measurements["magnitude_match"] is False


# ============================================================================================
#  FAIL: wrong-axis motion (commanded x, moved y)
# ============================================================================================

def test_wrong_axis_motion_fails():
    az = ActiveChallengeAnalyzer()
    frames = challenge_sequence("y", 15.0)  # tilt about Y...
    sig = az.analyze(_ctx(frames, _cmd("x", 15.0)))  # ...but X was commanded
    assert _susp(sig) >= 0.7
    assert sig.measurements["axis_match"] is False


# ============================================================================================
#  FAIL: photo-of-screen (double perspective) breaks single-homography consistency
# ============================================================================================

def test_double_perspective_fails_consistency():
    az = ActiveChallengeAnalyzer()
    frames = double_perspective_sequence()
    sig = az.analyze(_ctx(frames, _cmd("x", 14.0)))
    # bezel / double perspective -> no single homography fits -> flagged
    assert sig.measurements["single_homography_consistent"] is False
    assert _susp(sig) >= 0.7


# ============================================================================================
#  The discrimination assertion: PASS < every FAIL (fails against a constant)
# ============================================================================================

def test_pass_is_less_suspicious_than_all_failures():
    az = ActiveChallengeAnalyzer()
    good = _susp(az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0))))
    static = _susp(az.analyze(_ctx(static_challenge_sequence(), _cmd("x", 15.0))))
    wrong = _susp(az.analyze(_ctx(challenge_sequence("y", 15.0), _cmd("x", 15.0))))
    screen = _susp(az.analyze(_ctx(double_perspective_sequence(), _cmd("x", 14.0))))
    assert good < static
    assert good < wrong
    assert good < screen


# ============================================================================================
#  Angular-jerk sub-measurement (honest anti-automation, not anti-screen)
# ============================================================================================

def test_angular_jerk_separates_scripted_from_human():
    scripted = list(np.linspace(0, 15, 12))  # perfectly linear ramp (a bot)
    rng = np.random.default_rng(3)
    human = list(np.linspace(0, 15, 12) + rng.normal(0, 0.8, 12)
                 + 1.5 * np.sin(np.linspace(0, 6, 12)))
    assert angular_jerk_cv(scripted) < angular_jerk_cv(human)


def test_jerk_measurement_present_in_signal():
    az = ActiveChallengeAnalyzer()
    sig = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0)))
    assert "angular_jerk_cv" in sig.measurements
    assert "scripted_motion_suspected" in sig.measurements


# ============================================================================================
#  Honest non-coverage + fail-closed + contract
# ============================================================================================

def test_no_challenge_is_not_evaluated():
    az = ActiveChallengeAnalyzer()
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.extend(challenge_sequence("x", 15.0))
    assert az.applicable(ctx) is False  # no challenge published
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_insufficient_frames_is_not_evaluated():
    az = ActiveChallengeAnalyzer()
    frames = challenge_sequence("x", 15.0)[:2]
    ctx = _ctx(frames, _cmd("x", 15.0))
    assert az.applicable(ctx) is False
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_untrackable_document_fails_closed():
    az = ActiveChallengeAnalyzer()
    # featureless frames: nothing to track -> cannot verify -> NOT_EVALUATED (never a pass)
    blank = [np.full((300, 300, 3), 128, np.uint8) for _ in range(6)]
    sig = az.analyze(_ctx(blank, _cmd("x", 15.0)))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_malformed_challenge_is_not_evaluated():
    az = ActiveChallengeAnalyzer()
    frames = challenge_sequence("x", 15.0)
    sig = az.analyze(_ctx(frames, {"axis": "z", "magnitude_deg": 15.0}))  # invalid axis
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_challenge_is_the_high_weight_anchor():
    az = ActiveChallengeAnalyzer()
    sig = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0)))
    assert sig.weight == settings.weight_active_challenge
    assert sig.producing_mode == Mode.CAMERA
    assert sig.layer == 4


def test_honest_bound_documents_injection_gap():
    az = ActiveChallengeAnalyzer()
    sig = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0)))
    assert "injection" in sig.measurements["honest_bound"].lower()


# ============================================================================================
#  reason_code — the plain-language mapping key for the live-capture guidance UI (not the
#  technical `reason` string, which stays verbatim for the underwriter evidence console)
# ============================================================================================

def test_reason_code_matches_each_branch():
    az = ActiveChallengeAnalyzer()
    passing = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0)))
    # the synthetic fixture is a perfectly linear ramp -> flagged as scripted-smooth (a real, honest
    # sub-signal, see test_angular_jerk_separates_scripted_from_human) -> the "clean pass, but
    # mechanically smooth" reason_code, not the unconditional "live_ok" (a human hand is never this
    # linear; that reason_code is exercised implicitly whenever jerk_cv clears _JERK_SCRIPTED_MAX).
    assert passing.measurements["reason_code"] == "live_ok_scripted_suspected"

    screen = az.analyze(_ctx(double_perspective_sequence(), _cmd("x", 14.0)))
    assert screen.measurements["reason_code"] == "inconsistent_homography"

    # zero realised motion at all (a frozen replay) falls on the wrong AXIS: with realised ~0 deg on
    # both axes, neither clears the tolerance, so axis dominance can't be established either.
    static_replay = az.analyze(_ctx(static_challenge_sequence(), _cmd("x", 15.0)))
    assert static_replay.measurements["reason_code"] == "wrong_axis"

    wrong_axis = az.analyze(_ctx(challenge_sequence("y", 15.0), _cmd("x", 15.0)))
    assert wrong_axis.measurements["reason_code"] == "wrong_axis"

    # right axis, real motion realised, but well short of the commanded magnitude -> wrong_magnitude.
    wrong_mag = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 30.0)))
    assert wrong_mag.measurements["reason_code"] == "wrong_magnitude"
    # realised (~15) < commanded (30) -> needs MORE motion, not less
    assert wrong_mag.measurements["needs_more_or_less"] == "more"


def test_needs_more_or_less_only_present_on_wrong_magnitude():
    az = ActiveChallengeAnalyzer()
    passing = az.analyze(_ctx(challenge_sequence("x", 15.0), _cmd("x", 15.0)))
    assert "needs_more_or_less" not in passing.measurements
    screen = az.analyze(_ctx(double_perspective_sequence(), _cmd("x", 14.0)))
    assert "needs_more_or_less" not in screen.measurements


# ============================================================================================
#  Regression: a small document against a busy, static background must still PASS — a real user
#  holding an ID card against a real room (door, wall, their own face) is exactly this scenario,
#  and it was FALSELY flagged "inconsistent homography / photo-of-screen" before corner seeding
#  was restricted to the document's own quad (capture/challenge.py::_document_seed_mask).
# ============================================================================================

def test_small_document_over_busy_background_still_passes():
    az = ActiveChallengeAnalyzer()
    frames = small_document_over_busy_static_background("x", 15.0)
    sig = az.analyze(_ctx(frames, _cmd("x", 15.0)))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion <= 0.1, sig.reason
    assert sig.measurements["single_homography_consistent"] is True
    assert sig.measurements["axis_match"] is True
    assert sig.measurements["magnitude_match"] is True


def test_seed_mask_falls_back_to_center_crop_not_unmasked():
    """When contour-based quad detection fails outright (messy real-world lighting/shadows a
    synthetic fixture won't reproduce), seeding must still be BIASED toward the center — never
    silently fall back to the whole frame, which would reintroduce the background-outvoting bug."""
    frame = np.full((300, 300, 3), 128, np.uint8)  # no detectable quad in a flat frame
    with patch("capture.challenge.find_document_quad", return_value=None):
        mask = _document_seed_mask(frame)
    assert mask is not None
    # Matches the dedicated center-crop fallback, not an all-255 (fully unmasked) array.
    assert np.array_equal(mask, _center_crop_mask(frame))
    assert 0 < mask.sum() < mask.size * 255  # neither empty nor the whole frame
