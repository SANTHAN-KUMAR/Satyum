"""Tier-3 foundation: document boundary detect -> perspective rectify -> capture quality gate.

This is the *foundation* every other camera signal stands on (BUILD-MANIFEST: "Document boundary
detect + perspective rectify + quality gate"). On the most recent frame in ``ctx.frames`` it:

  1. finds the document quad — grayscale -> blur -> Canny edges -> largest convex 4-point
     ``approxPolyDP`` contour covering a meaningful fraction of the frame;
  2. perspective-corrects it with ``getPerspectiveTransform`` / ``warpPerspective`` to a
     fronto-parallel crop and publishes it at ``ctx.shared['rectified']`` for downstream reuse
     (pHash, arithmetic-on-camera, the anti-spoof votes);
  3. quality-gates the crop: focus via variance-of-Laplacian against
     ``settings.quality_min_laplacian_var`` and exposure via luma-clipping fractions.

Fail-closed (CLAUDE.md §4, BUILD-MANIFEST guard "poor capture must fail-closed to REVIEW, not
pass"): if no quad is found OR the crop is out of focus / badly exposed, this returns
``NOT_EVALUATED`` — the orchestrator excludes it from the score and the verdict degrades toward
REVIEW. A clean, in-focus, well-exposed capture returns ``VALID`` with low suspicion.

This analyzer measures *capture quality*, not authenticity — it never emits a high-suspicion
"tampered" verdict; its job is to decide whether the frame is good enough for the real detectors.

Honest bound: quad detection assumes the document is the dominant rectangular object against a
contrasting background. A document filling the whole frame (no visible border) yields no quad and
is honestly NOT_EVALUATED rather than mis-rectified.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

# --- named constants with provenance (CLAUDE.md §5 — no magic numbers) -----------------------
# All DEFAULT — needs calibration against a real capture corpus unless noted.
_CANNY_LOW = 50  # Canny hysteresis low threshold (px gradient)
_CANNY_HIGH = 150  # Canny hysteresis high threshold
_BLUR_KSIZE = 5  # Gaussian pre-blur kernel (odd) to suppress sensor noise before edges
_APPROX_EPS_FRAC = 0.02  # approxPolyDP epsilon as a fraction of contour perimeter
_MIN_QUAD_AREA_FRAC = 0.20  # a real document quad must cover >=20% of the frame
_TOP_CONTOURS = 6  # only inspect the largest few contours (perf + robustness)
_RECTIFIED_LONG_EDGE = 1000  # px; long edge of the rectified crop (downscale for speed, §7)
# Exposure gate: fraction of luma pixels allowed at the clipping rails before the frame is "bad".
_LUMA_DARK = 16  # 8-bit luma below this is "crushed shadow"
_LUMA_BRIGHT = 239  # above this is "blown highlight"
_MAX_CLIP_FRAC = 0.35  # >35% of pixels clipped at either rail -> unusable exposure

NAME = "capture_rectify_quality"
LAYER = 1
MODE = Mode.CAMERA
ORDER = 5

_HONEST_BOUND = (
    "measures capture quality (focus + exposure + a detectable document quad), not authenticity; "
    "poor capture fails closed to NOT_EVALUATED (REVIEW downstream), never a forced pass"
)


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """Order 4 corner points as TL, TR, BR, BL (the canonical destination order).

    Uses the classic sum/diff rule: TL has the smallest x+y, BR the largest; TR has the smallest
    x-y, BL the largest. Pure NumPy, deterministic.
    """
    pts = pts.astype(np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [
            pts[np.argmin(s)],  # top-left
            pts[np.argmin(d)],  # top-right
            pts[np.argmax(s)],  # bottom-right
            pts[np.argmax(d)],  # bottom-left
        ],
        dtype=np.float32,
    )


def find_document_quad(bgr: np.ndarray, min_area_frac: float = _MIN_QUAD_AREA_FRAC) -> np.ndarray | None:
    """Return the document's 4 corner points (float32, 4x2) or ``None`` if no quad is found.

    grayscale -> Gaussian blur -> Canny -> dilate -> external contours; the largest convex
    4-vertex polygon covering >= ``min_area_frac`` of the frame wins. ``min_area_frac`` defaults to
    this module's own quality-gate bar (``_MIN_QUAD_AREA_FRAC``); a caller with a lower bar (e.g.
    ``capture/challenge.py`` biasing corner-seed placement, where a missed/approximate quad only
    means falling back to unmasked seeding, never a false pass/fail) may pass a smaller value.
    """
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (_BLUR_KSIZE, _BLUR_KSIZE), 0)
    edges = cv2.Canny(gray, _CANNY_LOW, _CANNY_HIGH)
    # Close 1px gaps in the document border so approxPolyDP yields a clean closed quad.
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    frame_area = float(bgr.shape[0] * bgr.shape[1])
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:_TOP_CONTOURS]
    for c in contours:
        peri = cv2.arcLength(c, True)
        if peri <= 0:
            continue
        approx = cv2.approxPolyDP(c, _APPROX_EPS_FRAC * peri, True)
        if (
            len(approx) == 4
            and cv2.isContourConvex(approx)
            and cv2.contourArea(approx) >= min_area_frac * frame_area
        ):
            return _order_quad(approx)
    return None


def rectify(bgr: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Perspective-correct the document quad to a fronto-parallel crop.

    Destination size is derived from the measured edge lengths of the quad so the aspect ratio is
    preserved, then bounded to ``_RECTIFIED_LONG_EDGE`` for downstream speed.
    """
    tl, tr, br, bl = quad
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    width = max(int(round(width)), 1)
    height = max(int(round(height)), 1)

    # Bound the long edge for performance without distorting aspect ratio.
    scale = min(1.0, _RECTIFIED_LONG_EDGE / float(max(width, height)))
    out_w = max(int(round(width * scale)), 1)
    out_h = max(int(round(height * scale)), 1)

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    return cv2.warpPerspective(bgr, matrix, (out_w, out_h))


def focus_measure(gray: np.ndarray) -> float:
    """Variance of the Laplacian — the standard, deterministic focus/sharpness metric.

    A blurred crop has little high-frequency content, so the Laplacian response has low variance;
    a sharp, in-focus document has high variance. Higher = sharper.
    """
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def exposure_clip_fractions(gray: np.ndarray) -> tuple[float, float]:
    """Return (dark_clip_fraction, bright_clip_fraction) of the luma channel."""
    total = float(gray.size)
    dark = float(np.count_nonzero(gray <= _LUMA_DARK)) / total
    bright = float(np.count_nonzero(gray >= _LUMA_BRIGHT)) / total
    return dark, bright


def _quality_suspicion(lap_var: float, dark: float, bright: float) -> float:
    """Map focus headroom and exposure clipping to a low capture-quality suspicion in [0, 1].

    This stays low for any *usable* capture (the gate already rejected unusable ones); it nudges
    suspicion up modestly as the crop approaches the quality floor so a borderline-but-passing
    frame is not scored identically to a pristine one. It never asserts tampering.
    """
    floor = float(settings.quality_min_laplacian_var)
    # 0 at >=2x the focus floor, rising to ~0.5 as it approaches the floor.
    focus_term = max(0.0, min(0.5, 0.5 * (1.0 - (lap_var - floor) / floor)))
    clip_term = min(0.5, (dark + bright))  # residual exposure pressure
    return float(min(1.0, focus_term + clip_term))


class RectifyQualityAnalyzer:
    """Tier-3 capture foundation analyzer. Operates on the latest frame in ``ctx.frames``."""

    name = NAME
    layer = LAYER
    mode = MODE
    order = ORDER

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.CAMERA and bool(ctx.frames)

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if not ctx.frames:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no camera frames available"
            )
        frame = ctx.frames[-1]
        try:
            arr = np.asarray(frame)
            if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
                return LayerSignal.error(
                    self.name, self.layer, self.mode,
                    f"unexpected frame shape {getattr(arr, 'shape', None)} (need HxWx3 BGR)",
                )
            bgr = arr.astype(np.uint8, copy=False)

            quad = find_document_quad(bgr)
            if quad is None:
                # Fail-closed: no document boundary -> cannot rectify -> downstream REVIEW.
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    "no document quad detected in frame (fail-closed to REVIEW)",
                    honest_bound=_HONEST_BOUND,
                )

            rectified = rectify(bgr, quad)
            gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
            lap_var = focus_measure(gray)
            dark, bright = exposure_clip_fractions(gray)
        except cv2.error as exc:  # OpenCV internal failure -> fail-closed ERROR, never a pass
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"opencv failure: {exc}"
            )

        measurements: dict[str, Any] = {
            "laplacian_var": round(lap_var, 2),
            "focus_floor": float(settings.quality_min_laplacian_var),
            "dark_clip_frac": round(dark, 4),
            "bright_clip_frac": round(bright, 4),
            "rectified_shape": list(rectified.shape),
            "honest_bound": _HONEST_BOUND,
        }

        # Quality gates — any failure is fail-closed NOT_EVALUATED, never a forced pass.
        if lap_var < settings.quality_min_laplacian_var:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                f"out of focus: variance-of-Laplacian {lap_var:.1f} < "
                f"{settings.quality_min_laplacian_var:.1f} floor (fail-closed to REVIEW)",
                **measurements,
            )
        if (dark + bright) > _MAX_CLIP_FRAC:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                f"bad exposure: {(dark + bright) * 100:.0f}% of pixels clipped "
                f"(dark {dark * 100:.0f}% + bright {bright * 100:.0f}%) (fail-closed to REVIEW)",
                **measurements,
            )

        # Good capture: publish the rectified crop for downstream analyzers and pass with low
        # suspicion. Store a copy so no downstream analyzer can mutate our artifact (§4 immutability).
        ctx.shared["rectified"] = rectified.copy()
        ctx.shared["document_quad"] = quad.tolist()

        suspicion = _quality_suspicion(lap_var, dark, bright)
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            weight=0.0,  # capture quality is a gate/foundation, not a scored authenticity vote
            reason=(
                f"good capture: focus {lap_var:.0f} (>= {settings.quality_min_laplacian_var:.0f}), "
                f"exposure within bounds; rectified crop published"
            ),
            measurements=measurements,
        )
