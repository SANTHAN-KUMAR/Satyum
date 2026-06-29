"""Tier-2 forensics: spatial copy-move (region-clone) detection via ORB + RANSAC offset clustering.

What it catches: a forger copies a region of the document and pastes it elsewhere — a duplicated
signature, a cloned official stamp, a number cell copied over another to overwrite a figure, a
patched-over date. The pasted patch is *pixel-identical* (or near so) to its source, which classical
copy-move forensics exploits: dense keypoints inside the source and the paste describe the same
local texture, so they match each other, and crucially every such matched pair shares the **same
translation/affine offset** (the copy vector). A coherent cluster of equal-offset matches that is
spatially compact at both ends = a clone.

Real technique (CLAUDE.md §3.1, BUILD-MANIFEST "Spatial copy-move (ORB+RANSAC)"):
  1. ORB keypoints + binary descriptors on the grayscale document.
  2. Self KNN match (each descriptor against all others) with **Lowe's ratio test** to keep only
     confident, distinctive correspondences.
  3. **Exclude near-spatial-neighbours** — a keypoint's best non-self match is usually its own
     neighbour a few pixels away (texture continuity), which is NOT a clone. We drop any pair whose
     endpoints are closer than ``min_match_distance_px``.
  4. **Cluster by consistent offset** and fit a partial-affine model with RANSAC
     (``cv2.estimateAffinePartial2D``): a real clone yields many inliers sharing one translation;
     scattered coincidental matches do not.
  5. The two inlier point-clouds (source + paste) become the two flagged bounding boxes.

False-positive guards against *legitimately* repeated structure (the BUILD-MANIFEST must-not-flag
case — gridlines, logos, identical glyphs), because naive copy-move flags every repeated element:
  * a clone must have a **single dominant** offset cluster, not the many small/periodic offsets a
    ruled grid or a row of identical glyphs produces (we reject when inliers spread across many
    competing offsets);
  * the offset magnitude must exceed ``min_offset_px`` (tiny offsets = texture/grid repetition);
  * the source and paste clusters must each be **spatially compact** (a real pasted patch is a
    contiguous blob, not points sprinkled across the whole page like a repeating motif).

Honest bound: this finds *internal* clones, not a patch pasted from a *different* document (no shared
keypoints) — that residual is covered by provenance, arithmetic and resubmission memory. Low weight
(``settings.weight_copy_move``): a contributing vote, deliberately not a hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass
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
except ImportError as exc:  # pragma: no cover - exercised only on a broken install
    cv2 = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"OpenCV unavailable: {exc}"

# Identity documents (AADHAAR, PAN_CARD) repeat design elements by specification — the UIDAI logo,
# Ashoka pillar, and security watermarks appear multiple times, which causes copy-move's offset
# clustering to fire on genuine repetition. Skip these doc types to avoid false positives.
# Defined locally to avoid a circular import with intake.sufficiency.
_IDENTITY_DOC_TYPES: frozenset[str] = frozenset({"AADHAAR", "PAN_CARD"})

# --- Detector tunables. DEFAULT — needs calibration on a real corpus (CLAUDE.md §5). ----------
ORB_N_FEATURES = 4000          # dense enough to populate a small pasted patch with keypoints
LOWE_RATIO = 0.75              # Lowe's ratio test; standard distinctiveness gate for ORB matches
MIN_MATCH_DISTANCE_PX = 16.0   # endpoints closer than this are texture neighbours, not a clone
MIN_OFFSET_PX = 24.0           # copy vector shorter than this is grid/texture repetition, not a paste
RANSAC_REPROJ_PX = 4.0         # affine inlier tolerance
MIN_CLUSTER_INLIERS = 12       # a real clone is a dense correspondence cloud, not a few coincidences
# The winning offset cluster must dominate vs the many small periodic offsets that ruled grids /
# repeated logos / incidental near-duplicate glyphs produce. Measured separation on generated
# fixtures: clean & repetitive docs peak at <=0.13 dominant fraction, a real pasted clone sits at
# 0.41-0.78 — a wide gap. 0.30 sits in that gap (well above any clean case). DEFAULT — needs
# calibration on a real corpus, but the gap, not a tuned point, is what makes it discriminate.
MIN_DOMINANT_FRACTION = 0.30
MAX_CLUSTER_SPREAD_FRAC = 0.45 # each end must be spatially compact relative to the image diagonal
OFFSET_BIN_PX = 12.0           # offset-histogram bin width when finding the dominant copy vector


BBox = tuple[float, float, float, float]


@dataclass
class CopyMoveResult:
    evaluated: bool
    duplicated: bool
    inlier_count: int
    dominant_fraction: float
    source_bbox: BBox | None = None
    paste_bbox: BBox | None = None
    reason: str = ""


def _to_gray(image: Any) -> np.ndarray | None:
    if not isinstance(image, np.ndarray) or image.size == 0:
        return None
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY if image.shape[2] == 3 else cv2.COLOR_BGRA2GRAY)
    else:
        return None
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    return gray


def _bbox_of(points: np.ndarray) -> BBox:
    xs, ys = points[:, 0], points[:, 1]
    x0, y0 = float(xs.min()), float(ys.min())
    return (x0, y0, float(xs.max() - x0), float(ys.max() - y0))


def _spread_frac(points: np.ndarray, diag: float) -> float:
    """Cluster extent (bbox diagonal) as a fraction of the image diagonal — compactness measure."""
    x, y, w, h = _bbox_of(points)
    return float(np.hypot(w, h) / diag) if diag > 0 else 1.0


def detect_copy_move(gray: np.ndarray) -> CopyMoveResult:
    """Pure detection routine over a grayscale image. Deterministic given the same input.

    Returns ``evaluated=False`` when the image is too feature-poor to assert anything (honest gate,
    never a false "clean") and ``duplicated`` with both bounding boxes when a clone is found.
    """
    h, w = gray.shape[:2]
    diag = float(np.hypot(w, h))

    orb = cv2.ORB_create(nfeatures=ORB_N_FEATURES)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    if descriptors is None or len(keypoints) < MIN_CLUSTER_INLIERS * 2:
        return CopyMoveResult(
            evaluated=False, duplicated=False, inlier_count=0, dominant_fraction=0.0,
            reason="too few keypoints to assess duplication",
        )

    pts = np.array([kp.pt for kp in keypoints], dtype=np.float32)

    # Self KNN match: k=3 so we can skip the trivial self-match (index i -> i) and apply Lowe's
    # ratio against the next-best, on the genuine nearest neighbours.
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn = matcher.knnMatch(descriptors, descriptors, k=3)

    src_list: list[tuple[float, float]] = []
    dst_list: list[tuple[float, float]] = []
    for neighbours in knn:
        ordered = [m for m in neighbours if m.queryIdx != m.trainIdx]
        if len(ordered) < 2:
            continue
        best, second = ordered[0], ordered[1]
        # Lowe's ratio: the best non-self match must be clearly better than the runner-up.
        if best.distance >= LOWE_RATIO * max(second.distance, 1e-6):
            continue
        p, q = pts[best.queryIdx], pts[best.trainIdx]
        # Exclude near-spatial-neighbours (texture continuity), not a paste from elsewhere.
        if float(np.hypot(p[0] - q[0], p[1] - q[1])) < MIN_MATCH_DISTANCE_PX:
            continue
        src_list.append((float(p[0]), float(p[1])))
        dst_list.append((float(q[0]), float(q[1])))

    if len(src_list) < MIN_CLUSTER_INLIERS:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=len(src_list), dominant_fraction=0.0,
            reason="no coherent matched-offset cluster (clean / non-clonal)",
        )

    src = np.array(src_list, dtype=np.float32)
    dst = np.array(dst_list, dtype=np.float32)

    # --- Guard against periodic/repeated structure: find the DOMINANT translation offset. --------
    # A genuine clone shares one copy vector; a gridline/glyph row produces many periodic offsets.
    offsets = dst - src
    # The (p,q)/(q,p) symmetry of self-matching means each clone appears with +/- the same vector;
    # canonicalise by sign so the two halves reinforce one bin instead of splitting it.
    canon = offsets.copy()
    flip = (canon[:, 0] < 0) | ((canon[:, 0] == 0) & (canon[:, 1] < 0))
    canon[flip] *= -1
    bins = np.round(canon / OFFSET_BIN_PX).astype(np.int64)
    _, inverse, counts = np.unique(bins, axis=0, return_inverse=True, return_counts=True)
    dominant_bin = int(np.argmax(counts))
    dominant_fraction = float(counts[dominant_bin] / len(offsets))
    in_dominant = inverse == dominant_bin

    dom_src = src[in_dominant]
    dom_dst = dst[in_dominant]
    median_offset = np.median(dom_dst - dom_src, axis=0)
    if float(np.hypot(*median_offset)) < MIN_OFFSET_PX:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=int(in_dominant.sum()),
            dominant_fraction=dominant_fraction,
            reason="dominant offset below paste threshold (texture/grid repetition, not a clone)",
        )
    if dominant_fraction < MIN_DOMINANT_FRACTION:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=int(in_dominant.sum()),
            dominant_fraction=dominant_fraction,
            reason="matches spread across many offsets (repeated structure, not a single clone)",
        )

    # --- RANSAC: fit a partial-affine model to the dominant cluster; inliers are the real clone. --
    if len(dom_src) < MIN_CLUSTER_INLIERS:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=len(dom_src),
            dominant_fraction=dominant_fraction,
            reason="dominant offset cluster too small to confirm a clone",
        )
    model, inlier_mask = cv2.estimateAffinePartial2D(
        dom_src, dom_dst, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_REPROJ_PX,
    )
    if model is None or inlier_mask is None:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=0, dominant_fraction=dominant_fraction,
            reason="no consistent affine model for the matched cluster",
        )
    inliers = inlier_mask.ravel().astype(bool)
    n_inliers = int(inliers.sum())
    if n_inliers < MIN_CLUSTER_INLIERS:
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=n_inliers,
            dominant_fraction=dominant_fraction,
            reason="too few RANSAC inliers for a confident clone",
        )

    src_in = dom_src[inliers]
    dst_in = dom_dst[inliers]
    # Compactness guard: a pasted patch is a contiguous blob at both ends, not a page-wide motif.
    if (_spread_frac(src_in, diag) > MAX_CLUSTER_SPREAD_FRAC
            or _spread_frac(dst_in, diag) > MAX_CLUSTER_SPREAD_FRAC):
        return CopyMoveResult(
            evaluated=True, duplicated=False, inlier_count=n_inliers,
            dominant_fraction=dominant_fraction,
            reason="matched cluster not spatially compact (distributed repetition, not a paste)",
        )

    return CopyMoveResult(
        evaluated=True, duplicated=True, inlier_count=n_inliers,
        dominant_fraction=dominant_fraction,
        source_bbox=_bbox_of(src_in), paste_bbox=_bbox_of(dst_in),
        reason=f"coherent clone: {n_inliers} matched points share one copy offset",
    )


def _suspicion_from(result: CopyMoveResult) -> float:
    """More inliers and a more dominant single offset -> a more confident clone."""
    if not result.duplicated:
        return 0.0
    base = 0.6
    # extra inliers above the minimum and a clean dominant fraction both raise confidence
    inlier_bonus = min(0.25, 0.01 * (result.inlier_count - MIN_CLUSTER_INLIERS))
    dominance_bonus = 0.15 * max(0.0, result.dominant_fraction - MIN_DOMINANT_FRACTION)
    return float(min(1.0, base + inlier_bonus + dominance_bonus))


class CopyMoveAnalyzer:
    """Tier-2 analyzer wrapper. Operates on the rectified document image (``ctx.shared['rectified']``)."""

    name = "copy_move"
    layer = 3
    mode = Mode.ANY  # a clone is visible on a file page or a rectified camera crop alike
    order = 35

    def applicable(self, ctx: AnalysisContext) -> bool:
        doc_type = (ctx.doc_type or "").upper()
        if doc_type in _IDENTITY_DOC_TYPES:
            return False  # identity docs have genuine repeated design elements; skip to avoid false positives
        return self._source_image(ctx) is not None

    @staticmethod
    def _source_image(ctx: AnalysisContext) -> Any:
        for key in ("rectified", "page_image", "document_image"):
            img = ctx.shared.get(key)
            if isinstance(img, np.ndarray) and img.size > 0:
                return img
        return None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if _IMPORT_ERROR is not None:
            return LayerSignal.error(self.name, self.layer, self.mode, _IMPORT_ERROR)

        image = self._source_image(ctx)
        gray = _to_gray(image) if image is not None else None
        if gray is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no rectified/page image available for copy-move analysis",
            )

        try:
            result = detect_copy_move(gray)
        except cv2.error as exc:  # OpenCV failure -> fail-closed ERROR, never a silent pass
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv error: {exc}")

        if not result.evaluated:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, result.reason)

        suspicion = _suspicion_from(result)
        measurements: dict[str, Any] = {
            "inlier_count": result.inlier_count,
            "dominant_offset_fraction": round(result.dominant_fraction, 3),
            "duplicated": result.duplicated,
        }
        regions: list[EvidenceRegion] = []
        if result.duplicated and result.source_bbox and result.paste_bbox:
            regions = [
                EvidenceRegion(bbox=result.source_bbox, label="copy-move source region",
                               source=self.name),
                EvidenceRegion(bbox=result.paste_bbox, label="copy-move pasted region",
                               source=self.name),
            ]
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_copy_move, result.reason,
            evidence_regions=regions, measurements=measurements,
        )
