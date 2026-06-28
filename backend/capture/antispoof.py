"""Tier-3 anti-spoof votes (CAMERA): spectral moire, specular glare, temporal entropy.

Three independent, *contributing votes* (BUILD-MANIFEST: "Anti-spoof votes: moire FFT,
specular/glare, temporal entropy"). Each is individually beatable/confoundable — halftone-printed
genuine docs and banknotes also produce periodic FFT peaks; a matte screen suppresses glare; a
high-frame-rate replay carries temporal variance — so each carries only its configured weight and
is **never a hard gate**. The risk engine combines them; the Evidence Pack documents their
confoundability. When the frame buffer is too small to evaluate, a vote is honestly NOT_EVALUATED.

  * ``SpectralMoireAnalyzer`` — 2D FFT off-axis periodic-peak *prominence*. A re-imaged LCD/printed
    screen carries a high-frequency periodic carrier (subpixel grid / halftone / moire beat) that
    shows up as sharp off-DC spectral peaks; a diffuse page reflects a broadband, peak-free
    spectrum. We measure how far the strongest mid-band peak rises above the local median (robust
    MAD units), so the score genuinely tracks periodicity, not overall energy.
  * ``SpecularGlareAnalyzer`` — HSV saturation-clipped highlight statistics. A glossy screen
    reflects the ambient/illuminant as a *concentrated* blown-out specular hotspot (high V, low S);
    matte paper under even light shows no such clipped, contiguous hotspot. We measure the clipped
    fraction AND its concentration into a single blob.
  * ``TemporalEntropyAnalyzer`` — per-pixel temporal variance + loop autocorrelation across
    ``ctx.frames``. A static photo of a document has ~zero inter-frame variance (suspicious); a
    live capture has broadband micro-motion variance with low temporal autocorrelation; a looped
    replay has variance BUT a strong autocorrelation peak at the loop period (suspicious).

All three prefer ``ctx.shared['rectified']`` (the rectify analyzer's fronto-parallel crop) when
present so the votes operate on the document, not the background; they fall back to the raw frame.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

# ============================================================================================
#  Spectral moire (FFT)
# ============================================================================================
_MOIRE_LAYER = 1
# Mid-band radial window (fractions of the max radius) — excludes the DC/low-freq lighting gradient
# and the extreme high-freq sensor noise; the recapture carrier lives in this band.
_MOIRE_R_INNER = 0.15
_MOIRE_R_OUTER = 0.95
# Prominence (peak-over-median in MAD units) at/above which we treat the spectrum as carrying a
# recapture carrier. DEFAULT — needs calibration; halftone genuine docs can also exceed it, hence
# this is a *vote*, never a gate.
_MOIRE_PROMINENCE_FULL = 40.0  # prominence mapping saturates to suspicion ~1 here
_MOIRE_PROMINENCE_FLOOR = 8.0  # below this, no meaningful periodic peak -> ~0 suspicion
_MOIRE_MIN_SIDE = 64  # smallest analyzable crop edge


def moire_peak_prominence(gray: np.ndarray) -> float:
    """Prominence of the strongest mid-band spectral peak, in robust (MAD) units above the median.

    Hann-windowed (to kill spectral leakage / edge ringing), DC-removed 2D FFT magnitude; within an
    annular mid-frequency band, ``(max - median) / MAD``. A diffuse page -> small value; a periodic
    screen/halftone carrier -> large value. Higher = more periodic = more recapture-like.
    """
    g = gray.astype(np.float64)
    g = g - g.mean()
    win = np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
    g = g * win

    spectrum = np.fft.fftshift(np.fft.fft2(g))
    mag = np.abs(spectrum)

    h, w = mag.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    radius = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    rmax = float(min(cy, cx))
    if rmax <= 0:
        return 0.0
    band = (radius > _MOIRE_R_INNER * rmax) & (radius < _MOIRE_R_OUTER * rmax)
    vals = mag[band]
    if vals.size == 0:
        return 0.0
    median = float(np.median(vals))
    mad = float(np.median(np.abs(vals - median))) + 1e-9
    peak = float(vals.max())
    return (peak - median) / mad


def _prominence_to_suspicion(prominence: float) -> float:
    """Linear ramp from the floor to the full-suspicion prominence, clamped to [0, 1]."""
    if prominence <= _MOIRE_PROMINENCE_FLOOR:
        return 0.0
    span = _MOIRE_PROMINENCE_FULL - _MOIRE_PROMINENCE_FLOOR
    return float(min(1.0, (prominence - _MOIRE_PROMINENCE_FLOOR) / span))


# ============================================================================================
#  Specular glare (HSV)
# ============================================================================================
_GLARE_LAYER = 1
_GLARE_V_CLIP = 245  # HSV value at/above this is a blown highlight
_GLARE_S_MAX = 30  # ... with saturation below this (white specular, not coloured content)
# A concentrated hotspot covering this fraction of the crop maps to full glare suspicion.
_GLARE_HOTSPOT_FULL_FRAC = 0.05  # DEFAULT — needs calibration
_GLARE_MIN_CONCENTRATION = 0.4  # clipped area must be >=40% in one blob to count as a hotspot


def specular_glare_stats(bgr: np.ndarray) -> tuple[float, float, float]:
    """Return (clipped_fraction, concentration, hotspot_fraction).

    ``clipped_fraction`` = share of pixels that are blown specular highlights (high V, low S);
    ``concentration`` = share of that clipped area that lives in the single largest blob (a glare
    reflection is contiguous; faint diffuse clipping is scattered);
    ``hotspot_fraction`` = largest-blob area as a fraction of the crop.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    spec = ((val >= _GLARE_V_CLIP) & (sat <= _GLARE_S_MAX)).astype(np.uint8)
    total = int(spec.sum())
    size = float(spec.size)
    if total == 0:
        return 0.0, 0.0, 0.0
    num, _labels, stats, _ = cv2.connectedComponentsWithStats(spec, connectivity=8)
    if num <= 1:
        return total / size, 0.0, 0.0
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = float(areas.max())
    return total / size, largest / float(total), largest / size


def _glare_to_suspicion(clipped: float, concentration: float, hotspot: float) -> float:
    """A glare *hotspot* (concentrated, contiguous, blown) drives suspicion; scattered faint
    clipping does not. Returns [0, 1]."""
    if clipped == 0.0 or concentration < _GLARE_MIN_CONCENTRATION:
        return 0.0
    return float(min(1.0, hotspot / _GLARE_HOTSPOT_FULL_FRAC))


# ============================================================================================
#  Temporal entropy (per-pixel variance + loop autocorrelation)
# ============================================================================================
_TEMPORAL_LAYER = 1
_TEMPORAL_MIN_FRAMES = 4  # need a short sequence to assert anything about motion over time
# Below this mean per-pixel temporal variance the scene is effectively frozen (a static photo).
_TEMPORAL_STATIC_VAR = 1.0  # DEFAULT — needs calibration
_TEMPORAL_LIVE_VAR = 8.0  # at/above this, healthy live micro-motion variance
# Loop autocorrelation (at lag >= 2) at/above this signals a periodic replay loop.
_TEMPORAL_LOOP_AUTOCORR = 0.6  # DEFAULT — needs calibration
_TEMPORAL_MAX_SIDE = 256  # downscale frames for speed (§7); preserves global temporal stats


def _to_gray_small(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] == 3:
        gray = cv2.cvtColor(arr.astype(np.uint8, copy=False), cv2.COLOR_BGR2GRAY)
    else:
        gray = arr.astype(np.uint8, copy=False)
    h, w = gray.shape[:2]
    scale = min(1.0, _TEMPORAL_MAX_SIDE / float(max(h, w)))
    if scale < 1.0:
        gray = cv2.resize(gray, (max(int(w * scale), 1), max(int(h * scale), 1)),
                          interpolation=cv2.INTER_AREA)
    return gray.astype(np.float64)


def temporal_variance(frames: list[np.ndarray]) -> float:
    """Mean per-pixel variance across the (aligned) frame stack. ~0 == frozen image."""
    grays = [_to_gray_small(f) for f in frames]
    shape = grays[0].shape
    grays = [g for g in grays if g.shape == shape]
    if len(grays) < _TEMPORAL_MIN_FRAMES:
        return -1.0
    stack = np.stack(grays)
    return float(stack.var(axis=0).mean())


def loop_autocorrelation(frames: list[np.ndarray]) -> float:
    """Peak normalised autocorrelation (lag>=2) of the per-frame mean-intensity signal.

    A looped replay repeats a short clip, so the global signal is periodic -> high autocorrelation
    at the loop period. Live capture and a static photo are aperiodic -> low. Returns [0, 1]-ish.
    """
    grays = [_to_gray_small(f) for f in frames]
    shape = grays[0].shape
    grays = [g for g in grays if g.shape == shape]
    if len(grays) < _TEMPORAL_MIN_FRAMES:
        return 0.0
    signal = np.array([g.mean() for g in grays], dtype=np.float64)
    signal = signal - signal.mean()
    if np.allclose(signal, 0.0):
        return 0.0
    full = np.correlate(signal, signal, mode="full")
    autocorr = full[len(signal) - 1:]  # lags 0 .. n-1
    autocorr = autocorr / (autocorr[0] + 1e-12)
    if len(autocorr) <= 2:
        return 0.0
    return float(max(0.0, autocorr[2:].max()))


def _temporal_to_suspicion(var: float, loop_ac: float) -> float:
    """Static (frozen) OR looped (periodic) -> high suspicion; healthy aperiodic motion -> low."""
    if var < _TEMPORAL_STATIC_VAR:
        return 1.0  # a frozen frame buffer is a static photo of a document
    # Looped replay: variance present but periodic.
    loop_term = 0.0
    if loop_ac >= _TEMPORAL_LOOP_AUTOCORR:
        loop_term = float(min(1.0, loop_ac))
    # Borderline low (but non-zero) motion adds a little residual suspicion.
    motion_term = 0.0
    if var < _TEMPORAL_LIVE_VAR:
        motion_term = float(0.5 * (1.0 - (var - _TEMPORAL_STATIC_VAR) /
                                   (_TEMPORAL_LIVE_VAR - _TEMPORAL_STATIC_VAR)))
    return float(min(1.0, max(loop_term, motion_term)))


# ============================================================================================
#  Shared helpers + analyzer classes
# ============================================================================================
def _document_view(ctx: AnalysisContext) -> np.ndarray | None:
    """Prefer the rectified document crop; fall back to the latest raw frame."""
    rect = ctx.shared.get("rectified")
    if isinstance(rect, np.ndarray) and rect.ndim == 3 and rect.shape[2] == 3:
        return rect
    if ctx.frames:
        arr = np.asarray(ctx.frames[-1])
        if arr.ndim == 3 and arr.shape[2] == 3 and arr.size > 0:
            return arr.astype(np.uint8, copy=False)
    return None


_SPECTRAL_CONFOUND = (
    "vote only — halftone-printed genuine documents and security-printed notes also carry periodic "
    "FFT peaks; never a standalone gate"
)
_SPECULAR_CONFOUND = (
    "vote only — a matte screen or polarised capture suppresses glare and bright paper under harsh "
    "light can clip; never a standalone gate"
)
_TEMPORAL_CONFOUND = (
    "vote only — a high-frame-rate fresh replay carries micro-motion variance; this separates a "
    "frozen image and a short loop, not every replay; never a standalone gate"
)


class SpectralMoireAnalyzer:
    """Off-axis periodic-peak prominence vote (re-imaged screen / halftone recapture)."""

    name = "antispoof_spectral_moire"
    layer = _MOIRE_LAYER
    mode = Mode.CAMERA

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.CAMERA and _document_view(ctx) is not None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        view = _document_view(ctx)
        if view is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no document view (rectified crop or frame)"
            )
        try:
            gray = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
            if min(gray.shape[:2]) < _MOIRE_MIN_SIDE:
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    f"crop too small for FFT analysis ({gray.shape[:2]} < {_MOIRE_MIN_SIDE})",
                )
            prominence = moire_peak_prominence(gray)
        except cv2.error as exc:
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv failure: {exc}")

        suspicion = _prominence_to_suspicion(prominence)
        measurements: dict[str, Any] = {
            "peak_prominence_mad": round(prominence, 2),
            "prominence_floor": _MOIRE_PROMINENCE_FLOOR,
            "confound": _SPECTRAL_CONFOUND,
        }
        reason = (
            f"spectral peak prominence {prominence:.1f} MAD — "
            + ("periodic recapture carrier (screen/halftone) likely" if suspicion > 0
               else "broadband, no periodic recapture carrier")
        )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_antispoof_spectral, reason, measurements=measurements,
        )


class SpecularGlareAnalyzer:
    """Concentrated specular-highlight (glare) vote (glossy screen reflection)."""

    name = "antispoof_specular_glare"
    layer = _GLARE_LAYER
    mode = Mode.CAMERA

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.CAMERA and _document_view(ctx) is not None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        view = _document_view(ctx)
        if view is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no document view (rectified crop or frame)"
            )
        try:
            clipped, concentration, hotspot = specular_glare_stats(view)
        except cv2.error as exc:
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv failure: {exc}")

        suspicion = _glare_to_suspicion(clipped, concentration, hotspot)
        measurements: dict[str, Any] = {
            "clipped_fraction": round(clipped, 4),
            "concentration": round(concentration, 3),
            "hotspot_fraction": round(hotspot, 4),
            "confound": _SPECULAR_CONFOUND,
        }
        reason = (
            f"specular: {clipped * 100:.1f}% clipped, concentration {concentration:.2f} — "
            + ("concentrated glare hotspot (screen reflection) present" if suspicion > 0
               else "no concentrated specular hotspot")
        )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_antispoof_specular, reason, measurements=measurements,
        )


class TemporalEntropyAnalyzer:
    """Per-pixel temporal variance + loop autocorrelation vote (static image / looped replay)."""

    name = "antispoof_temporal_entropy"
    layer = _TEMPORAL_LAYER
    mode = Mode.CAMERA

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.CAMERA and len(ctx.frames) >= _TEMPORAL_MIN_FRAMES

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if len(ctx.frames) < _TEMPORAL_MIN_FRAMES:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                f"need >= {_TEMPORAL_MIN_FRAMES} frames for temporal analysis "
                f"(have {len(ctx.frames)})",
            )
        try:
            var = temporal_variance(ctx.frames)
            if var < 0.0:  # frames not shape-consistent / too few aligned
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode,
                    "frames not shape-consistent for temporal analysis",
                )
            loop_ac = loop_autocorrelation(ctx.frames)
        except cv2.error as exc:
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv failure: {exc}")

        suspicion = _temporal_to_suspicion(var, loop_ac)
        measurements: dict[str, Any] = {
            "temporal_variance": round(var, 3),
            "static_var_floor": _TEMPORAL_STATIC_VAR,
            "loop_autocorr": round(loop_ac, 3),
            "loop_autocorr_threshold": _TEMPORAL_LOOP_AUTOCORR,
            "confound": _TEMPORAL_CONFOUND,
        }
        if var < _TEMPORAL_STATIC_VAR:
            reason = f"frozen frame buffer (temporal variance {var:.2f}) — static photo of document"
        elif loop_ac >= _TEMPORAL_LOOP_AUTOCORR:
            reason = f"periodic loop (autocorr {loop_ac:.2f}) — replayed video loop likely"
        else:
            reason = f"live aperiodic micro-motion (variance {var:.1f}, autocorr {loop_ac:.2f})"
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_antispoof_temporal, reason, measurements=measurements,
        )
