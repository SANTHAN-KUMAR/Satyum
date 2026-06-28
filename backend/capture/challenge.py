"""Tier-4 CENTERPIECE (CAMERA): the active server-randomized 3D challenge-response.

The anti-replay anchor (ADR-003 / BUILD-MANIFEST: "Active server-randomized 3D challenge"). A
pre-recorded video or a photo-of-screen cannot satisfy a command the server only issues *after*
the session starts. The server publishes a just-in-time, unpredictable command at
``ctx.shared['challenge']`` — an axis ('x' = tilt up/down, 'y' = pan left/right), a signed
magnitude in degrees, a direction, and a deadline. We then:

  1. track the document across ``ctx.frames`` — ``goodFeaturesToTrack`` seeds corners on the first
     frame, ``calcOpticalFlowPyrLK`` follows them frame-to-frame;
  2. fit a single per-sequence homography (first -> last) from the tracked correspondences with
     ``findHomography(RANSAC)`` and decompose it (``decomposeHomographyMat``) to recover the
     REALISED rotation about each axis;
  3. verify the realised tilt matches the COMMANDED axis+magnitude within
     ``settings.challenge_homography_tol_deg``, AND that a *single consistent homography* explains
     the motion (high RANSAC inlier ratio + low reprojection residual). A photo-of-screen carries
     the screen's bezel / a double perspective, so no single planar homography fits — it fails the
     consistency test even if the gross motion looks right.
  4. derive an angular-jerk sub-measurement: a scripted/automated tilt is an unnaturally smooth
     ramp (near-zero jerk); a human hand produces irregular jerk. This is HONEST anti-automation
     corroboration, NOT anti-screen — it is reported separately and weighted on its own.

Verdict mapping: a correct, consistent, commanded motion -> low suspicion (live document). Wrong
axis / wrong magnitude / inconsistent homography -> high suspicion. Insufficient frames or an
untrackable document -> NOT_EVALUATED (fail-closed to REVIEW downstream), never a forced pass.

Honest bound: this defeats *presentation* replay (pre-recorded clip, photo-of-screen), not stream
*injection* (a virtual camera feeding a synthetic response) — injection needs native platform
attestation and is handled as a separate, low-weight, documented-bypassable check (BUILD-MANIFEST).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import cv2
import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

NAME = "active_challenge"
LAYER = 4
MODE = Mode.CAMERA
ORDER = 10

# --- named constants with provenance (CLAUDE.md §5) — DEFAULT, needs calibration -------------
_MIN_FRAMES = 4  # need a short motion sequence to fit a homography
_MAX_CORNERS = 200  # goodFeaturesToTrack cap
_CORNER_QUALITY = 0.01  # goodFeaturesToTrack qualityLevel
_CORNER_MIN_DIST = 6  # goodFeaturesToTrack minDistance (px)
_MIN_TRACKED = 12  # minimum surviving correspondences to fit a homography
_RANSAC_REPROJ_PX = 3.0  # findHomography RANSAC reprojection threshold
# Single-homography consistency: a real planar document gives a near-1.0 inlier ratio and sub-px
# residual; a photo-of-screen (bezel / double perspective) breaks one or both.
_MIN_INLIER_RATIO = 0.6
_MAX_MEDIAN_RESIDUAL_PX = 6.0
# Default focal length as a multiple of the image long edge when intrinsics are unknown — a
# standard webcam approximation (~60 deg HFOV). The recovered ANGLE is only weakly sensitive to it,
# and both commanded and realised angles use the same K, so the comparison stays fair.
_FOCAL_LONG_EDGE_MULT = 1.2
# Angular-jerk: coefficient-of-variation of angular jerk below this looks machine-smooth (scripted).
_JERK_SCRIPTED_MAX = 0.15  # DEFAULT — needs calibration on real human-vs-bot captures

_HONEST_BOUND = (
    "defeats presentation replay (pre-recorded clip / photo-of-screen via single-homography "
    "consistency), NOT stream injection (virtual camera) — injection needs native platform "
    "attestation and is a separate low-weight, documented-bypassable check"
)
_JERK_NOTE = (
    "angular-jerk is anti-automation corroboration (a scripted ramp is unnaturally smooth), NOT "
    "anti-screen; reported and weighted separately"
)


def _intrinsics(width: int, height: int) -> np.ndarray:
    """Approximate camera intrinsics when none are provided (typical webcam HFOV)."""
    f = _FOCAL_LONG_EDGE_MULT * float(max(width, height))
    return np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _to_gray(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] == 3:
        return cv2.cvtColor(arr.astype(np.uint8, copy=False), cv2.COLOR_BGR2GRAY)
    return arr.astype(np.uint8, copy=False)


def track_corners(frames: list[np.ndarray]) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Track features from the first to the last frame via pyramidal Lucas-Kanade optical flow.

    Returns ``(start_pts, end_pts)`` of the surviving correspondences (Nx2 float32), or ``None`` if
    the document could not be seeded/tracked. Points are chained frame-to-frame so the end points
    correspond to the same physical features as the start points.
    """
    g0 = _to_gray(frames[0])
    seed = cv2.goodFeaturesToTrack(
        g0, maxCorners=_MAX_CORNERS, qualityLevel=_CORNER_QUALITY, minDistance=_CORNER_MIN_DIST
    )
    if seed is None or len(seed) < _MIN_TRACKED:
        return None

    start = seed.copy()
    cur = seed.copy()
    g_prev = g0
    alive = np.ones((len(seed), 1), dtype=bool)

    for frame in frames[1:]:
        g = _to_gray(frame)
        nxt, status, _err = cv2.calcOpticalFlowPyrLK(g_prev, g, cur, None)
        if nxt is None or status is None:
            return None
        ok = status.astype(bool)
        alive = alive & ok
        cur = nxt
        g_prev = g

    alive = alive.ravel()
    if int(alive.sum()) < _MIN_TRACKED:
        return None
    return (
        start[alive].reshape(-1, 2).astype(np.float32),
        cur[alive].reshape(-1, 2).astype(np.float32),
    )


def homography_consistency(start: np.ndarray, end: np.ndarray) -> tuple[Optional[np.ndarray], float, float]:
    """Fit one homography start->end and measure how well a SINGLE plane explains the motion.

    Returns ``(H, inlier_ratio, median_residual_px)``. A genuine flat document moving rigidly gives
    a high inlier ratio and a small residual; a photo-of-screen (two perspectives) does not.
    """
    matrix, mask = cv2.findHomography(start, end, cv2.RANSAC, _RANSAC_REPROJ_PX)
    if matrix is None or mask is None:
        return None, 0.0, math.inf
    inlier_ratio = float(mask.mean())
    projected = cv2.perspectiveTransform(start.reshape(-1, 1, 2).astype(np.float64),
                                         matrix).reshape(-1, 2)
    residuals = np.linalg.norm(projected - end, axis=1)
    return matrix, inlier_ratio, float(np.median(residuals))


def recover_axis_angles(matrix: np.ndarray, intrinsics: np.ndarray) -> dict[str, float]:
    """Decompose a homography into the realised tilt angles (deg) about the x and y axes.

    ``decomposeHomographyMat`` returns up to four (R, t, n) solutions; we take, per axis, the
    largest-magnitude rotation component across solutions (the dominant realised rotation).
    """
    _num, rotations, _t, _n = cv2.decomposeHomographyMat(matrix, intrinsics)
    best = {"x": 0.0, "y": 0.0}
    for rotation in rotations:
        rvec, _ = cv2.Rodrigues(rotation)
        ax = math.degrees(abs(float(rvec[0, 0])))
        ay = math.degrees(abs(float(rvec[1, 0])))
        best["x"] = max(best["x"], ax)
        best["y"] = max(best["y"], ay)
    return best


def per_frame_axis_series(frames: list[np.ndarray], start: np.ndarray,
                          intrinsics: np.ndarray, axis: str) -> list[float]:
    """Recover the realised tilt angle about ``axis`` at each frame (relative to the first).

    Used only for the angular-jerk sub-measurement — it characterises the *shape* of the motion
    over time, independent of the final-angle pass/fail check.
    """
    g0 = _to_gray(frames[0])
    cur = start.reshape(-1, 1, 2).astype(np.float32)
    g_prev = g0
    series = [0.0]
    for frame in frames[1:]:
        g = _to_gray(frame)
        nxt, status, _err = cv2.calcOpticalFlowPyrLK(g_prev, g, cur, None)
        if nxt is None or status is None:
            break
        ok = status.ravel().astype(bool)
        if int(ok.sum()) < _MIN_TRACKED:
            break
        a = start[ok].astype(np.float32)
        b = nxt.reshape(-1, 2)[ok].astype(np.float32)
        matrix, _mask = cv2.findHomography(a, b, cv2.RANSAC, _RANSAC_REPROJ_PX)
        if matrix is None:
            series.append(series[-1])
        else:
            series.append(recover_axis_angles(matrix, intrinsics)[axis])
        cur = nxt
        g_prev = g
    return series


def angular_jerk_cv(angle_series: list[float]) -> float:
    """Coefficient-of-variation of angular jerk (3rd difference) normalised by mean speed.

    A scripted linear/constant-accel ramp has ~zero jerk -> ~0; a human hand's irregular motion has
    high jerk variability -> larger. Returns >= 0. Honest anti-automation, not anti-screen.
    """
    a = np.asarray(angle_series, dtype=np.float64)
    if len(a) < 4:
        return 0.0
    velocity = np.diff(a)
    jerk = np.diff(np.diff(velocity))
    speed = float(np.abs(velocity).mean()) + 1e-9
    return float(np.abs(jerk).std() / speed)


def _suspicion(axis_ok: bool, magnitude_ok: bool, consistent: bool) -> float:
    """Map the three pass/fail conditions to a challenge suspicion in [0, 1]."""
    if axis_ok and magnitude_ok and consistent:
        return 0.05  # commanded motion realised on a single consistent plane -> live document
    if not consistent:
        return 0.95  # inconsistent homography -> photo-of-screen / double perspective
    if not axis_ok:
        return 0.9  # motion on the wrong axis -> not the commanded challenge (replay/random)
    return 0.75  # right axis, wrong magnitude -> challenge not satisfied


def _validate_challenge(challenge: Any) -> Optional[tuple[str, float]]:
    """Return (axis, magnitude_deg) from the server challenge, or None if malformed."""
    if not isinstance(challenge, dict):
        return None
    axis = challenge.get("axis")
    magnitude = challenge.get("magnitude_deg", challenge.get("magnitude"))
    if axis not in ("x", "y") or not isinstance(magnitude, (int, float)):
        return None
    return axis, abs(float(magnitude))


class ActiveChallengeAnalyzer:
    """Tier-4 active 3D challenge-response — the centerpiece anti-replay anchor."""

    name = NAME
    layer = LAYER
    mode = MODE
    order = ORDER

    def applicable(self, ctx: AnalysisContext) -> bool:
        return (
            ctx.intake_mode == Mode.CAMERA
            and len(ctx.frames) >= _MIN_FRAMES
            and isinstance(ctx.shared.get("challenge"), dict)
        )

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        challenge = _validate_challenge(ctx.shared.get("challenge"))
        if challenge is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no valid server challenge issued (need axis in {x,y} + magnitude_deg)",
            )
        if len(ctx.frames) < _MIN_FRAMES:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                f"need >= {_MIN_FRAMES} frames (have {len(ctx.frames)})",
            )
        cmd_axis, cmd_mag = challenge
        other_axis = "y" if cmd_axis == "x" else "x"

        try:
            tracked = track_corners(ctx.frames)
            if tracked is None:
                # Cannot track the document -> cannot verify the challenge -> fail-closed.
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    "document could not be tracked across frames (fail-closed to REVIEW)",
                    honest_bound=_HONEST_BOUND,
                )
            start, end = tracked
            h0 = _to_gray(ctx.frames[0])
            intrinsics = _intrinsics(h0.shape[1], h0.shape[0])

            matrix, inlier_ratio, residual = homography_consistency(start, end)
            if matrix is None:
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    "no homography could be fit from tracked points (fail-closed to REVIEW)",
                    honest_bound=_HONEST_BOUND,
                )

            angles = recover_axis_angles(matrix, intrinsics)
            jerk_cv = angular_jerk_cv(
                per_frame_axis_series(ctx.frames, start, intrinsics, cmd_axis)
            )
        except cv2.error as exc:
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv failure: {exc}")

        realised_cmd = angles[cmd_axis]
        realised_other = angles[other_axis]
        tol = float(settings.challenge_homography_tol_deg)

        consistent = inlier_ratio >= _MIN_INLIER_RATIO and residual <= _MAX_MEDIAN_RESIDUAL_PX
        # Commanded axis dominates: realised motion is on the commanded axis, not the other one.
        axis_ok = realised_cmd >= (realised_other + tol) or (
            realised_cmd >= tol and realised_other <= tol
        )
        magnitude_ok = abs(realised_cmd - cmd_mag) <= tol

        suspicion = _suspicion(axis_ok, magnitude_ok, consistent)
        scripted = jerk_cv < _JERK_SCRIPTED_MAX

        measurements: dict[str, Any] = {
            "commanded_axis": cmd_axis,
            "commanded_magnitude_deg": round(cmd_mag, 2),
            "realised_commanded_axis_deg": round(realised_cmd, 2),
            "realised_other_axis_deg": round(realised_other, 2),
            "tolerance_deg": tol,
            "inlier_ratio": round(inlier_ratio, 3),
            "median_residual_px": round(residual, 2),
            "single_homography_consistent": consistent,
            "axis_match": axis_ok,
            "magnitude_match": magnitude_ok,
            "angular_jerk_cv": round(jerk_cv, 4),
            "scripted_motion_suspected": scripted,
            "honest_bound": _HONEST_BOUND,
            "jerk_note": _JERK_NOTE,
        }

        if suspicion <= 0.1 and scripted:
            reason = (
                f"commanded {cmd_axis}-tilt {cmd_mag:.0f} deg realised ({realised_cmd:.1f} deg) on a "
                f"consistent plane, BUT motion is unnaturally smooth (jerk CV {jerk_cv:.2f}) — "
                f"possible automation"
            )
        elif suspicion <= 0.1:
            reason = (
                f"commanded {cmd_axis}-tilt {cmd_mag:.0f} deg realised ({realised_cmd:.1f} deg) on a "
                f"single consistent homography (inliers {inlier_ratio:.2f}) — live document"
            )
        elif not consistent:
            reason = (
                f"homography inconsistent (inliers {inlier_ratio:.2f}, residual {residual:.1f}px) — "
                f"double perspective / photo-of-screen"
            )
        elif not axis_ok:
            reason = (
                f"motion on the wrong axis: commanded {cmd_axis} but realised {cmd_axis}="
                f"{realised_cmd:.1f} deg vs {other_axis}={realised_other:.1f} deg — challenge unmet"
            )
        else:
            reason = (
                f"wrong magnitude: commanded {cmd_mag:.0f} deg, realised {realised_cmd:.1f} deg "
                f"(tol {tol:.0f}) — challenge unmet"
            )

        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_active_challenge, reason, measurements=measurements,
        )
