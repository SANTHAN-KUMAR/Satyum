"""Discrimination tests for the CENTERPIECE active 3D challenge-response analyzer.

The BUILD-MANIFEST must-pass guard: "photo-of-screen replay FAILS; live tilt matching the command
PASSES; wrong-direction motion FAILS." Each test fails against a constant return — no fixed
suspicion can make a matching tilt low-suspicion while a static replay, a wrong-axis tilt, and an
inconsistent double-perspective are all high-suspicion.
"""

from __future__ import annotations

import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, Mode, SignalStatus
from capture.challenge import (
    ActiveChallengeAnalyzer,
    angular_jerk_cv,
    homography_consistency,
    recover_axis_angles,
    track_corners,
)
from tests.capture_fixtures import (
    challenge_sequence,
    double_perspective_sequence,
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
