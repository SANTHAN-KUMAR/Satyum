"""Tier-2 forensics: font / layout / alignment anomaly from per-word OCR geometry.

What it catches: a spliced or retyped field. When a forger edits one value on a statement — overwrites
a salary figure, swaps a name, changes an account number — the replacement text rarely matches the
surrounding line's typography to sub-pixel precision. Its baseline sits a little high or low, its
glyphs are a touch taller/shorter (different x-height / point size), or its strokes are heavier or
lighter (a different font weight or a re-rasterised paste). Genuine machine-set text on one line is
remarkably uniform in all three; the edited word is a statistical outlier against its own line.

Real technique (CLAUDE.md §3.1, BUILD-MANIFEST "Font/layout/alignment anomaly"):
  * Per-word geometry from ``ctx.shared['ocr']`` (or raw Tesseract ``image_to_data``): bbox + the
    line/block it belongs to.
  * Group words into text lines; within each line measure three independent typographic features:
      - **baseline offset**  — word bottom (top+height) vs the line's robust baseline,
      - **x-height**         — the word's glyph height vs the line's typical height,
      - **stroke width**     — the mean of the distance transform over the word's ink pixels
                               (a thicker stroke = a larger interior distance), normalised by height
                               so it is point-size invariant.
  * For each feature, a **robust z-score** (median / MAD) of every word against its line. A word that
    is a strong outlier on one or more features is flagged with a confidence proportional to how far
    out it is — *evidence with confidence, not a binary gate* (the BUILD-MANIFEST requirement).

False-positive discipline: short tokens (1-2 chars) and low-OCR-confidence words are excluded from
flagging (their geometry is unreliable); a line needs enough words to have a stable median before we
trust an outlier call. Honest bound: this finds typographic *discontinuity*, not a forgery that was
re-typeset uniformly (e.g. the whole document regenerated) — that residual is the arithmetic engine's
and provenance's job. Low weight (``settings.weight_font_layout``): a contributing vote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.config import settings
from app.contracts import (
    AnalysisContext,
    EvidenceRegion,
    LayerSignal,
    Mode,
)

try:
    import cv2

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"OpenCV unavailable: {exc}"

# Identity documents use multi-font, multi-script UIDAI/NSDL layouts. The z-score baselines here
# are calibrated on financial statements; running them on Aadhaar/PAN produces high false-positive
# rates (35+ words "anomalous" on a genuine UIDAI card). Skip these doc types entirely.
# Defined locally to avoid a circular import with intake.sufficiency.
_IDENTITY_DOC_TYPES: frozenset[str] = frozenset({"AADHAAR", "PAN_CARD"})

# --- Detector tunables. DEFAULT — needs calibration on a real corpus (CLAUDE.md §5). ----------
MIN_WORD_CHARS = 3          # 1-2 char tokens have unstable geometry -> excluded from flagging
MIN_OCR_CONF = 0.0          # words below this confidence are excluded (unreliable geometry)
MIN_WORDS_PER_LINE = 4      # need a stable per-line median before an outlier call is trustworthy
ROBUST_Z_FLAG = 3.0         # robust z (via MAD) beyond this on any feature = outlier
# Typography tolerances are RELATIVE to glyph size: a deviation only matters as a fraction of the
# line's text height. These floors set the minimum meaningful deviation per feature so (a) a
# genuinely uniform line (MAD ~ 0) cannot turn sub-pixel OCR jitter into a huge z-score (the
# degenerate-MAD trap), and (b) ordinary glyph-composition variance — a word with an ascender or
# descender ('Opening', 'Closing') legitimately gives Tesseract a ~25-30% taller box and lower
# baseline than 'Balance' — does NOT read as tampering. Measured on real Tesseract output: at a
# 0.20*median-height floor, descender variance reads z~1.5 while a realistic cross-document paste
# (a field noticeably larger/shifted) reads z~3.3 — a real margin, not a tuned point. The floors
# are a fraction of the line's median word height. DEFAULT — needs calibration on a real corpus.
BASELINE_SCALE_FLOOR_FRAC = 0.20
HEIGHT_SCALE_FLOOR_FRAC = 0.20
STROKE_SCALE_FLOOR = 0.02          # stroke width is already height-normalised (~0..0.5); absolute floor
# A single moderate outlier is weak; combined/extreme outliers are strong. Map max-z -> suspicion.
SUSPICION_AT_FLAG = 0.45    # suspicion when a word just reaches ROBUST_Z_FLAG on one feature
SUSPICION_Z_SLOPE = 0.10    # extra suspicion per unit of robust-z above the flag threshold


@dataclass
class WordGeom:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float
    line_key: tuple[int, int]  # (block_num, line_num)
    baseline: float = 0.0          # top + height
    stroke_width: float = 0.0      # normalised mean distance-transform over ink
    # populated during analysis
    z_baseline: float = 0.0
    z_height: float = 0.0
    z_stroke: float = 0.0
    flagged: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class LayoutResult:
    evaluated: bool
    words_considered: int
    flagged: list[WordGeom] = field(default_factory=list)
    max_z: float = 0.0
    reason: str = ""


def words_from_tesseract(data: dict[str, list]) -> list[dict[str, Any]]:
    """Normalise a Tesseract ``image_to_data(output_type=DICT)`` result into OCR word dicts.

    Published as the ``ctx.shared['ocr']`` schema so this analyzer and the arithmetic parser share
    one shape: each word is ``{text,left,top,width,height,conf,line_num,block_num}``.
    """
    out: list[dict[str, Any]] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        raw_conf = data["conf"][i]
        conf = float(raw_conf) / 100.0 if float(raw_conf) >= 0 else 0.0
        out.append(
            {
                "text": text,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "conf": conf,
                "line_num": int(data.get("line_num", [0] * n)[i]),
                "block_num": int(data.get("block_num", [0] * n)[i]),
            }
        )
    return out


def _stroke_width(gray: np.ndarray, word: dict[str, Any]) -> float:
    """Mean stroke half-width of a word, via the distance transform of its ink mask.

    The distance transform gives, for every ink pixel, its distance to the nearest background pixel;
    averaged over the ink it scales with stroke thickness. Normalised by glyph height so it compares
    across point sizes. Returns 0.0 when the crop has no ink (handled by the caller).
    """
    x, y = max(0, word["left"]), max(0, word["top"])
    w, h = word["width"], word["height"]
    crop = gray[y:y + h, x:x + w]
    if crop.size == 0 or h <= 0:
        return 0.0
    # Otsu threshold -> ink is the darker class. THRESH_BINARY_INV makes ink = 255.
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if int(np.count_nonzero(ink)) == 0:
        return 0.0
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    mean_half_width = float(dist[ink > 0].mean())
    return mean_half_width / float(h)  # point-size invariant


def _robust_z(values: np.ndarray, scale_floor: float) -> np.ndarray:
    """Robust z-score using median and MAD (resistant to the very outlier we're hunting).

    ``scale_floor`` is the minimum meaningful deviation for this feature (a typographic tolerance
    in the feature's own units). It prevents a near-uniform line (MAD ~ 0) from amplifying sub-pixel
    OCR/anti-alias jitter into a spurious huge z-score — the degenerate-MAD false-positive trap.
    """
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    scale = max(1.4826 * float(mad), scale_floor)  # 1.4826*MAD ~ sigma for normals; floored
    return (values - med) / scale


def analyze_layout(words: list[dict[str, Any]], gray: np.ndarray | None) -> LayoutResult:
    """Per-line typographic outlier detection. Pure function over OCR words + optional image.

    Without the image, stroke width can't be measured, so only baseline and x-height are used
    (still a real, discriminating signal). With the image, all three features contribute.
    """
    geoms: list[WordGeom] = []
    for w in words:
        text = str(w.get("text", "")).strip()
        if len(text) < MIN_WORD_CHARS:
            continue
        conf = float(w.get("conf", 1.0))
        if conf < MIN_OCR_CONF:
            continue
        g = WordGeom(
            text=text, left=int(w["left"]), top=int(w["top"]),
            width=int(w["width"]), height=int(w["height"]), conf=conf,
            line_key=(int(w.get("block_num", 0)), int(w.get("line_num", 0))),
        )
        g.baseline = g.top + g.height
        if gray is not None:
            g.stroke_width = _stroke_width(gray, w)
        geoms.append(g)

    if not geoms:
        return LayoutResult(evaluated=False, words_considered=0,
                            reason="no usable words for layout analysis")

    # Group by text line.
    lines: dict[tuple[int, int], list[WordGeom]] = {}
    for g in geoms:
        lines.setdefault(g.line_key, []).append(g)

    flagged: list[WordGeom] = []
    max_z = 0.0
    lines_assessed = 0
    for line_words in lines.values():
        if len(line_words) < MIN_WORDS_PER_LINE:
            continue  # too few words to trust a per-line median
        lines_assessed += 1

        baselines = np.array([g.baseline for g in line_words], dtype=np.float64)
        heights = np.array([float(g.height) for g in line_words], dtype=np.float64)
        # Scale floors are tied to the line's text size so tolerances are typographically relative.
        median_height = float(np.median(heights)) or 1.0
        z_base = _robust_z(baselines, BASELINE_SCALE_FLOOR_FRAC * median_height)
        z_height = _robust_z(heights, HEIGHT_SCALE_FLOOR_FRAC * median_height)
        have_stroke = gray is not None and any(g.stroke_width > 0 for g in line_words)
        if have_stroke:
            strokes = np.array([g.stroke_width for g in line_words], dtype=np.float64)
            z_stroke = _robust_z(strokes, STROKE_SCALE_FLOOR)
        else:
            z_stroke = np.zeros(len(line_words))

        for i, g in enumerate(line_words):
            g.z_baseline = float(z_base[i])
            g.z_height = float(z_height[i])
            g.z_stroke = float(z_stroke[i])
            if abs(g.z_baseline) >= ROBUST_Z_FLAG:
                g.reasons.append(f"baseline z={g.z_baseline:+.1f}")
            if abs(g.z_height) >= ROBUST_Z_FLAG:
                g.reasons.append(f"x-height z={g.z_height:+.1f}")
            if have_stroke and abs(g.z_stroke) >= ROBUST_Z_FLAG:
                g.reasons.append(f"stroke z={g.z_stroke:+.1f}")
            if g.reasons:
                g.flagged = True
                flagged.append(g)
            word_max_z = max(abs(g.z_baseline), abs(g.z_height), abs(g.z_stroke))
            max_z = max(max_z, word_max_z if g.flagged else 0.0)

    if lines_assessed == 0:
        return LayoutResult(
            evaluated=False, words_considered=len(geoms),
            reason=f"no line had >= {MIN_WORDS_PER_LINE} usable words to assess",
        )

    return LayoutResult(
        evaluated=True, words_considered=len(geoms), flagged=flagged, max_z=max_z,
        reason=(f"{lines_assessed} line(s) assessed, {len(flagged)} word(s) typographically anomalous"),
    )


def _suspicion_from(result: LayoutResult) -> float:
    if not result.flagged:
        return 0.0
    over = max(0.0, result.max_z - ROBUST_Z_FLAG)
    base = SUSPICION_AT_FLAG + SUSPICION_Z_SLOPE * over
    # multiple independently anomalous words raise confidence (a single one could be OCR jitter)
    multi = 0.10 * (len(result.flagged) - 1)
    return float(min(1.0, base + multi))


class FontLayoutAnalyzer:
    """Tier-2 analyzer. Reads OCR word geometry (``ctx.shared['ocr']``) + the rectified image."""

    name = "font_layout"
    layer = 3
    mode = Mode.ANY  # operates on read geometry, valid on a file page or a rectified crop
    order = 32

    def applicable(self, ctx: AnalysisContext) -> bool:
        doc_type = (ctx.doc_type or "").upper()
        if doc_type in _IDENTITY_DOC_TYPES:
            return False  # z-score baselines calibrated for financial statements; not valid for identity docs
        ocr = ctx.shared.get("ocr")
        return isinstance(ocr, list) and len(ocr) > 0

    @staticmethod
    def _gray(ctx: AnalysisContext) -> np.ndarray | None:
        for key in ("rectified", "page_image", "document_image"):
            img = ctx.shared.get(key)
            if isinstance(img, np.ndarray) and img.size > 0:
                if img.ndim == 2:
                    out = img
                elif img.ndim == 3 and img.shape[2] in (3, 4):
                    code = cv2.COLOR_BGR2GRAY if img.shape[2] == 3 else cv2.COLOR_BGRA2GRAY
                    out = cv2.cvtColor(img, code)
                else:
                    continue
                return out if out.dtype == np.uint8 else np.clip(out, 0, 255).astype(np.uint8)
        return None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if _IMPORT_ERROR is not None:
            return LayerSignal.error(self.name, self.layer, self.mode, _IMPORT_ERROR)

        ocr = ctx.shared.get("ocr")
        if not isinstance(ocr, list) or not ocr:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no OCR word geometry available"
            )

        gray = self._gray(ctx)
        try:
            result = analyze_layout(ocr, gray)
        except (cv2.error, KeyError, ValueError, TypeError) as exc:  # malformed OCR -> fail-closed
            return LayerSignal.error(self.name, self.layer, self.mode, f"layout analysis failed: {exc}")

        if not result.evaluated:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, result.reason)

        suspicion = _suspicion_from(result)
        regions = [
            EvidenceRegion(
                bbox=(float(g.left), float(g.top), float(g.width), float(g.height)),
                label=f"typographic outlier '{g.text}' ({'; '.join(g.reasons)})",
                source=self.name,
            )
            for g in result.flagged
        ]
        measurements: dict[str, Any] = {
            "words_considered": result.words_considered,
            "flagged_count": len(result.flagged),
            "max_robust_z": round(result.max_z, 2),
            "flagged_words": [
                {"text": g.text, "z_baseline": round(g.z_baseline, 2),
                 "z_height": round(g.z_height, 2), "z_stroke": round(g.z_stroke, 2)}
                for g in result.flagged
            ],
        }
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_font_layout, result.reason,
            evidence_regions=regions, measurements=measurements,
        )
