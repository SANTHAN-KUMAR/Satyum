"""Tier-2 forensics: template fingerprinting against a corpus of known-bank layouts.

The idea: every bank statement / official form has a stable visual *skeleton* — header block, logo
placement, column rules, footer — that genuine documents from that issuer share and that an ad-hoc
forgery (or a wrong-issuer paste) does not reproduce structurally. Matching a document's structural
keypoints against a small library of known templates tells us (a) which issuer's template it is and
how well it fits, and (b) when a document claims to be from issuer X but its layout matches none of
the known templates — a structural mismatch worth flagging.

Real technique (CLAUDE.md §3.1, BUILD-MANIFEST "Template fingerprinting"):
  * ORB keypoints/descriptors per template (a real reference corpus) and per query document.
  * Brute-force Hamming match + Lowe's ratio test; the count of good matches against each template
    measures structural similarity. The best template above a match floor is the identified layout.

THE HONEST GATE (BUILD-MANIFEST, explicit): this is *only* meaningful with a genuine multi-template
corpus. "Fingerprint one sample and match it against itself" is a silent no-op (CLAUDE.md §3.2). So:
  * an **empty corpus -> NOT_EVALUATED** with the precise reason — never a fabricated pass;
  * a single-template corpus is allowed to *identify* but its absence-of-match is weak, and we say so.

The corpus is dependency-injected (``TemplateLibrary``) so it can be loaded from the issuer-capability
DB in production and constructed in-memory for tests, and so the analyzer never ships a hardcoded
"match" with no real references behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from app.config import settings
from app.contracts import (
    AnalysisContext,
    LayerSignal,
    Mode,
)

try:
    import cv2

    _IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    _IMPORT_ERROR = f"OpenCV unavailable: {exc}"

# --- Detector tunables. DEFAULT — needs calibration on a real corpus (CLAUDE.md §5). ----------
ORB_N_FEATURES = 1500
LOWE_RATIO = 0.75
# Recognition uses a MATCH RATIO (good matches / min keypoint count), which is stable across
# documents of differing feature density — unlike a raw count, which just scales with keypoints and
# lets a feature-dense unrelated page accrue enough coincidental matches to look recognised.
MIN_GOOD_MATCHES = 20       # absolute floor: fewer than this is too sparse to assert a match at all
MIN_MATCH_RATIO = 0.40      # measured: same-template ~0.69, different-bank ~0.25, unrelated <0.10
SUSPICION_NO_MATCH = 0.55   # document matches NO known template -> structurally unfamiliar (evidence)


@dataclass
class TemplateEntry:
    template_id: str
    issuer: str
    descriptors: np.ndarray  # ORB descriptors precomputed for the reference template


@dataclass
class TemplateMatch:
    template_id: str
    issuer: str
    good_matches: int
    match_ratio: float = 0.0  # good_matches / min(query_kp, template_kp) — density-stable score


@dataclass
class TemplateResult:
    evaluated: bool
    corpus_size: int
    best: Optional[TemplateMatch] = None
    recognised: bool = False
    reason: str = ""
    scores: list[TemplateMatch] = field(default_factory=list)


def _orb():
    return cv2.ORB_create(nfeatures=ORB_N_FEATURES)


def compute_descriptors(gray: np.ndarray) -> Optional[np.ndarray]:
    """ORB descriptors for an image, or None if too few keypoints to fingerprint."""
    _, des = _orb().detectAndCompute(gray, None)
    return des


class TemplateLibrary:
    """Injected corpus of known-bank templates. Empty by default -> the analyzer gates honestly."""

    def __init__(self) -> None:
        self._entries: list[TemplateEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def add_template(self, template_id: str, issuer: str, gray: np.ndarray) -> None:
        des = compute_descriptors(gray)
        if des is None or len(des) == 0:
            raise ValueError(f"template '{template_id}' produced no ORB descriptors")
        self._entries.append(TemplateEntry(template_id, issuer, des))

    @property
    def entries(self) -> list[TemplateEntry]:
        return list(self._entries)


def _good_match_count(query_des: np.ndarray, template_des: np.ndarray) -> int:
    """Lowe-ratio-filtered good matches between query and a template's descriptors."""
    if query_des is None or len(query_des) < 2 or len(template_des) < 2:
        return 0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn = matcher.knnMatch(query_des, template_des, k=2)
    good = 0
    for pair in knn:
        if len(pair) < 2:
            continue
        best, second = pair
        if best.distance < LOWE_RATIO * max(second.distance, 1e-6):
            good += 1
    return good


def match_template(gray: np.ndarray, library: TemplateLibrary) -> TemplateResult:
    """Match a document against the template corpus. Empty corpus -> evaluated=False (honest gate)."""
    if len(library) == 0:
        return TemplateResult(
            evaluated=False, corpus_size=0,
            reason="no template corpus available — template fingerprinting NOT evaluated",
        )

    query_des = compute_descriptors(gray)
    if query_des is None or len(query_des) < 2:
        return TemplateResult(
            evaluated=False, corpus_size=len(library),
            reason="document produced too few structural keypoints to fingerprint",
        )

    scores: list[TemplateMatch] = []
    for e in library.entries:
        good = _good_match_count(query_des, e.descriptors)
        denom = max(1, min(len(query_des), len(e.descriptors)))
        scores.append(TemplateMatch(e.template_id, e.issuer, good, good / denom))
    scores.sort(key=lambda m: m.match_ratio, reverse=True)
    best = scores[0]
    recognised = best.good_matches >= MIN_GOOD_MATCHES and best.match_ratio >= MIN_MATCH_RATIO
    return TemplateResult(
        evaluated=True, corpus_size=len(library), best=best, recognised=recognised,
        scores=scores,
        reason=(
            f"matched template '{best.template_id}' ({best.issuer}) at ratio "
            f"{best.match_ratio:.2f} ({best.good_matches} structural matches)" if recognised
            else (f"no known template recognised (best ratio {best.match_ratio:.2f} < "
                  f"{MIN_MATCH_RATIO})")
        ),
    )


class TemplateFingerprintAnalyzer:
    """Tier-2 FILE analyzer. Matches the document layout against an injected template corpus.

    FILE mode: a structural template fingerprint is a file-document concept; a live camera frame
    goes through rectification first and is handled on the ANY/camera detectors. With no corpus it
    returns NOT_EVALUATED — the BUILD-MANIFEST-mandated honest gate, never a fake pass.
    """

    name = "template_fingerprint"
    layer = 3
    mode = Mode.FILE
    order = 31

    def __init__(self, library: Optional[TemplateLibrary] = None) -> None:
        self._library = library if library is not None else TemplateLibrary()

    def applicable(self, ctx: AnalysisContext) -> bool:
        # Always applicable in FILE mode; it returns NOT_EVALUATED itself when the corpus is empty
        # so the empty-corpus honesty is visible in the evidence pack rather than silently skipped.
        return True

    @staticmethod
    def _gray(ctx: AnalysisContext) -> Optional[np.ndarray]:
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

        if len(self._library) == 0:
            # The headline honest gate: no real corpus -> excluded from the score, shown as pending.
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no known-bank template corpus loaded — fingerprinting requires a real corpus",
                corpus_size=0,
            )

        gray = self._gray(ctx)
        if gray is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no rectified/page image available for template matching",
                corpus_size=len(self._library),
            )

        try:
            result = match_template(gray, self._library)
        except cv2.error as exc:  # OpenCV failure -> fail-closed ERROR
            return LayerSignal.error(self.name, self.layer, self.mode, f"opencv error: {exc}")

        if not result.evaluated:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, result.reason,
                corpus_size=result.corpus_size,
            )

        # Recognised layout -> structurally familiar (low suspicion); no match -> unfamiliar layout
        # is weak evidence the document isn't a genuine instance of any known issuer template.
        suspicion = 0.0 if result.recognised else SUSPICION_NO_MATCH
        measurements: dict[str, Any] = {
            "corpus_size": result.corpus_size,
            "recognised": result.recognised,
            "best_template": result.best.template_id if result.best else None,
            "best_issuer": result.best.issuer if result.best else None,
            "best_good_matches": result.best.good_matches if result.best else 0,
            "best_match_ratio": round(result.best.match_ratio, 3) if result.best else 0.0,
            "min_good_matches": MIN_GOOD_MATCHES,
            "min_match_ratio": MIN_MATCH_RATIO,
            "scores": [
                {"template_id": m.template_id, "issuer": m.issuer,
                 "good_matches": m.good_matches, "match_ratio": round(m.match_ratio, 3)}
                for m in result.scores
            ],
        }
        if result.recognised and result.best is not None:
            ctx.shared["matched_template"] = {
                "template_id": result.best.template_id, "issuer": result.best.issuer,
            }
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion,
            settings.weight_template_fingerprint, result.reason,
            measurements=measurements,
        )
