"""Tier-2 resubmission / fraud-ring memory: perceptual-hash match against a fraud-hash store.

The thesis (CLAUDE.md §1, ADR-003 point 4): a forged document is rarely used once. The same
fabricated statement is recycled across applicants in a fraud ring, or the identical artefact is
re-submitted after a first rejection — sometimes lightly rescaled, recompressed, or blurred to
dodge an exact-byte hash. A *perceptual* hash (DCT-based pHash) collapses those benign
transformations to a near-identical fingerprint while staying far from an unrelated document, so a
Hamming-distance lookup against a store of known-fraud hashes catches the reuse.

Real technique (no fake signal — CLAUDE.md §3.1):
  * ``imagehash.phash(img, hash_size=16)`` — a 256-bit DCT perceptual hash of the rectified/cropped
    document. It survives rescale and mild blur because the DCT keeps the low-frequency structure.
  * Hamming distance (``ImageHash.__sub__``) against every entry in an injected ``PhashStore``; the
    smallest distance within ``settings.phash_hamming_threshold`` is a resubmission hit, and we
    return the matched session id so the underwriter can pull the prior case.

Honest bound: pHash matches *visual layout*, not identity — two genuine borrowers using the same
blank bank template are visually similar but differ in the printed figures, which a 256-bit pHash
at a calibrated radius separates. The threshold is ``# DEFAULT — needs calibration`` from a real
ROC (BUILD-MANIFEST: "threshold must be traceable to it") until the corpus exists; it is named in
config, never a magic literal here.

The ``PhashStore`` is dependency-injected (in-memory or SQLite-backed) so the analyzer is testable
without a database and the production store can be encrypted at rest (CLAUDE.md §10).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app.config import settings
from app.contracts import (
    AnalysisContext,
    EvidenceRegion,
    LayerSignal,
    Mode,
)

# Heavy deps are pinned in requirements.txt; import each independently so a missing one degrades to
# a clean ERROR (never a silent pass) and one absent library never nulls the other.
try:
    from PIL import Image

    _PIL_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - exercised only on a broken install
    Image = None  # type: ignore[assignment]
    _PIL_ERROR = f"Pillow unavailable: {exc}"

try:
    import imagehash

    _IMAGEHASH_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - exercised only on a broken install
    imagehash = None  # type: ignore[assignment]
    _IMAGEHASH_ERROR = f"imagehash unavailable: {exc}"

_IMPORT_ERROR: str | None = _PIL_ERROR or _IMAGEHASH_ERROR

# pHash geometry. hash_size=16 -> 16x16 DCT-derived bits = a 256-bit hash, which is what the
# settings.phash_hamming_threshold comment is calibrated against. Named, not magic (CLAUDE.md §5).
PHASH_HASH_SIZE = 16
PHASH_BITS = PHASH_HASH_SIZE * PHASH_HASH_SIZE


@dataclass(frozen=True)
class FraudMatch:
    session_id: str
    distance: int
    label: str


class PhashStore(Protocol):
    """Injected fraud-hash store. Implementations: in-memory (tests) or SQLite (production)."""

    def add(self, session_id: str, hash_hex: str, label: str = "") -> None: ...

    def nearest(self, hash_hex: str, max_distance: int) -> FraudMatch | None:
        """Return the closest stored fraud hash within ``max_distance`` Hamming bits, or None."""
        ...


def _hamming(hex_a: str, hex_b: str) -> int:
    """Hamming distance between two pHash hex strings, via the real imagehash reconstruction.

    ``imagehash``'s subtraction yields a ``numpy.int64``; we cast to a native ``int`` so the value
    is JSON-serialisable when it lands in ``LayerSignal.measurements`` (``model_dump(mode="json")``
    on the result-delivery path raises ``PydanticSerializationError`` on a raw numpy scalar — and a
    resubmission hit is exactly the case we must surface, not crash on).
    """
    return int(imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b))


class InMemoryPhashStore:
    """Reference store for tests and small deployments. Linear scan over known-fraud hashes."""

    def __init__(self) -> None:
        self._entries: list[tuple[str, str, str]] = []  # (session_id, hash_hex, label)

    def add(self, session_id: str, hash_hex: str, label: str = "") -> None:
        self._entries.append((session_id, hash_hex, label))

    def nearest(self, hash_hex: str, max_distance: int) -> FraudMatch | None:
        best: FraudMatch | None = None
        for session_id, stored_hex, label in self._entries:
            distance = _hamming(hash_hex, stored_hex)
            if distance <= max_distance and (best is None or distance < best.distance):
                best = FraudMatch(session_id=session_id, distance=distance, label=label)
        return best


class SqlitePhashStore:
    """SQLite-backed fraud-hash store. Still a linear Hamming scan (256-bit space is tiny per row);
    a production deployment would shard by hash prefix, but the lookup semantics are identical.

    The DB holds only hashes + metadata — never document content or imagery (CLAUDE.md §10). The
    caller is responsible for encrypting the file at rest.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS fraud_phash "
            "(session_id TEXT NOT NULL, hash_hex TEXT NOT NULL, label TEXT DEFAULT '')"
        )
        self._conn.commit()

    def add(self, session_id: str, hash_hex: str, label: str = "") -> None:
        self._conn.execute(
            "INSERT INTO fraud_phash (session_id, hash_hex, label) VALUES (?, ?, ?)",
            (session_id, hash_hex, label),
        )
        self._conn.commit()

    def nearest(self, hash_hex: str, max_distance: int) -> FraudMatch | None:
        best: FraudMatch | None = None
        for session_id, stored_hex, label in self._conn.execute(
            "SELECT session_id, hash_hex, label FROM fraud_phash"
        ):
            distance = _hamming(hash_hex, stored_hex)
            if distance <= max_distance and (best is None or distance < best.distance):
                best = FraudMatch(session_id=session_id, distance=distance, label=label)
        return best


def _to_pil(image: Any) -> Image.Image | None:
    """Coerce a rectified document image (np.ndarray BGR/gray or PIL) to a PIL grayscale image.

    pHash is colour-agnostic and we want robustness to the BGR/RGB ambiguity of an upstream
    OpenCV crop, so we hash a single luminance channel.
    """
    if Image is None:
        return None
    if isinstance(image, np.ndarray):
        arr = image
        if arr.ndim == 3:
            # Average channels to luminance — order-independent, so BGR vs RGB cannot change it.
            arr = arr.mean(axis=2)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, mode="L")
    if Image is not None and isinstance(image, Image.Image):
        return image.convert("L")
    return None


def compute_phash_hex(image: Any) -> str | None:
    """Compute the 256-bit pHash hex of a document image, or None if it can't be coerced."""
    pil = _to_pil(image)
    if pil is None:
        return None
    return str(imagehash.phash(pil, hash_size=PHASH_HASH_SIZE))


class PhashResubmissionAnalyzer:
    """Tier-2 analyzer. Hashes the rectified document and looks it up in an injected fraud store.

    The store is injected so the analyzer is unit-testable and the production store (SQLite,
    encrypted at rest) is swappable without touching this class.
    """

    name = "phash_resubmission"
    layer = 3
    mode = Mode.ANY  # a pHash is medium-agnostic: a file page or a rectified camera crop
    order = 40

    def __init__(self, store: PhashStore | None = None) -> None:
        self._store: PhashStore = store if store is not None else InMemoryPhashStore()

    def applicable(self, ctx: AnalysisContext) -> bool:
        return self._source_image(ctx) is not None

    @staticmethod
    def _source_image(ctx: AnalysisContext) -> Any:
        # Prefer the rectified crop; fall back to a raw page image an upstream stage published.
        for key in ("rectified", "page_image", "document_image"):
            img = ctx.shared.get(key)
            if isinstance(img, np.ndarray) and img.size > 0:
                return img
            if Image is not None and isinstance(img, Image.Image):
                return img
        return None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if _IMPORT_ERROR is not None:
            return LayerSignal.error(self.name, self.layer, self.mode, _IMPORT_ERROR)

        image = self._source_image(ctx)
        if image is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no rectified/page image available to hash",
            )

        try:
            query_hex = compute_phash_hex(image)
        except (ValueError, TypeError, OSError) as exc:  # malformed image -> fail-closed ERROR
            return LayerSignal.error(self.name, self.layer, self.mode, f"phash failed: {exc}")
        if query_hex is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "image could not be coerced to a hashable form"
            )

        threshold = int(settings.phash_hamming_threshold)
        try:
            match = self._store.nearest(query_hex, threshold)
        except (sqlite3.Error, ValueError) as exc:  # store failure -> fail-closed, never silent pass
            return LayerSignal.error(self.name, self.layer, self.mode, f"fraud-store lookup failed: {exc}")

        # Publish the computed hash so downstream stages (cross-document graph, audit) can reuse it.
        ctx.shared["phash_hex"] = query_hex

        measurements: dict[str, Any] = {
            "phash_hex": query_hex,
            "hash_bits": PHASH_BITS,
            "hamming_threshold": threshold,
            "matched": match is not None,
            "threshold_note": "DEFAULT — needs ROC calibration on a real fraud corpus",
        }

        if match is None:
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=0.0,
                weight=settings.weight_phash_resubmission,
                reason="no perceptual match in the fraud-hash store",
                measurements=measurements,
            )

        # A resubmission hit. Suspicion is high and rises as the match gets tighter (closer to an
        # identical artefact); it stays meaningful out to the threshold radius.
        closeness = 1.0 - (match.distance / max(threshold, 1))
        suspicion = float(min(1.0, 0.80 + 0.20 * max(0.0, closeness)))
        measurements.update(
            {"matched_session_id": match.session_id, "hamming_distance": match.distance,
             "matched_label": match.label}
        )
        region = EvidenceRegion(
            bbox=(0.0, 0.0, 0.0, 0.0),  # whole-document fingerprint match, not a sub-region
            label=(
                f"perceptual match to known fraud session {match.session_id} "
                f"(Hamming {match.distance}/{threshold})"
            ),
            source=self.name,
        )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion=suspicion,
            weight=settings.weight_phash_resubmission,
            reason=(
                f"resubmission: perceptual hash within {match.distance} bits of known fraud "
                f"session {match.session_id}"
            ),
            evidence_regions=[region], measurements=measurements,
        )
