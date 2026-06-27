"""Discrimination tests for the pHash resubmission detector.

The claim under test: the SAME document, rescaled / mildly blurred, perceptually matches a seeded
fraud hash (within ``settings.phash_hamming_threshold``), while an UNRELATED document does not. This
fails against any constant — a resubmission must raise suspicion while an unrelated doc keeps it at
0; no constant satisfies both. Fixtures are generated programmatically (CLAUDE.md §3.2 / §8).

The perceptual-hash discrimination tests use the real ``imagehash`` library (pinned in
requirements.txt) and are skipped only if it is not installed in the runtime; the store / Hamming
logic is tested with no heavy dependency so it runs everywhere.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from app.config import settings
from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.phash import (
    InMemoryPhashStore,
    PhashResubmissionAnalyzer,
    SqlitePhashStore,
)

imagehash = pytest.importorskip("imagehash")  # real perceptual hashing; pinned in requirements


# --- programmatic image fixtures -----------------------------------------------------------------

def _document(seed: int) -> np.ndarray:
    """A distinctive synthetic document (structured text/box pattern) seeded for reproducibility."""
    import cv2

    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 255, np.uint8)
    cv2.rectangle(img, (20, 20), (620, 90), (0, 0, 0), 3)
    for i in range(10):
        y = 120 + i * 32
        cv2.line(img, (20, y), (620, y), (0, 0, 0), 1)
        cv2.putText(img, f"TXN {rng.integers(1000, 9999)}  Rs {rng.integers(100, 99999)}",
                    (30, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def _rescaled_then_blurred(img: np.ndarray) -> np.ndarray:
    """The same document, downscaled+upscaled and mildly blurred — a resubmission evasion attempt."""
    import cv2

    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    back = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(back, (3, 3), 0)


# --- perceptual robustness: the core claim -------------------------------------------------------

def test_same_document_rescaled_blurred_matches_seeded_fraud():
    original = _document(seed=7)
    store = InMemoryPhashStore()
    # Seed the fraud store with the ORIGINAL document's hash (a prior rejected submission).
    original_hex = str(imagehash.phash(_to_pil(original), hash_size=16))
    store.add("prior-fraud-session-7", original_hex, label="ring-A")

    az = PhashResubmissionAnalyzer(store=store)
    # The resubmission is a rescaled + blurred copy — a different file, same document.
    resubmitted = _rescaled_then_blurred(original)
    ctx = _ctx(resubmitted)
    sig = az.analyze(ctx)

    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion >= 0.8, "a resubmission must read as suspicious"
    assert sig.measurements["matched"] is True
    assert sig.measurements["matched_session_id"] == "prior-fraud-session-7"
    assert sig.measurements["hamming_distance"] <= settings.phash_hamming_threshold
    assert sig.evidence_regions, "a matched resubmission must carry an evidence region"


def test_unrelated_document_does_not_match():
    store = InMemoryPhashStore()
    store.add("prior-fraud-session-7", str(imagehash.phash(_to_pil(_document(7)), hash_size=16)))

    az = PhashResubmissionAnalyzer(store=store)
    unrelated = _document(seed=999)  # a structurally different document
    sig = az.analyze(_ctx(unrelated))

    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0, "an unrelated genuine document must not match the fraud store"
    assert sig.measurements["matched"] is False


def test_analyzer_discriminates_resubmission_vs_unrelated():
    # The single discriminating assertion: same suspicion is impossible across the two inputs.
    store = InMemoryPhashStore()
    store.add("p7", str(imagehash.phash(_to_pil(_document(7)), hash_size=16)))
    az = PhashResubmissionAnalyzer(store=store)

    hit = az.analyze(_ctx(_rescaled_then_blurred(_document(7)))).suspicion
    miss = az.analyze(_ctx(_document(999))).suspicion
    assert hit != miss
    assert hit > miss


def test_empty_store_yields_clean_not_match():
    az = PhashResubmissionAnalyzer(store=InMemoryPhashStore())
    sig = az.analyze(_ctx(_document(7)))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0


def test_phash_published_to_shared_for_downstream():
    az = PhashResubmissionAnalyzer(store=InMemoryPhashStore())
    ctx = _ctx(_document(7))
    az.analyze(ctx)
    assert isinstance(ctx.shared.get("phash_hex"), str)


def test_sqlite_store_backend_matches_same_document():
    conn = sqlite3.connect(":memory:")
    store = SqlitePhashStore(conn)
    store.add("sql-fraud-1", str(imagehash.phash(_to_pil(_document(7)), hash_size=16)), "ring-B")
    az = PhashResubmissionAnalyzer(store=store)
    sig = az.analyze(_ctx(_rescaled_then_blurred(_document(7))))
    assert sig.measurements["matched"] is True
    assert sig.measurements["matched_session_id"] == "sql-fraud-1"


def test_analyzer_not_evaluated_without_image():
    az = PhashResubmissionAnalyzer(store=InMemoryPhashStore())
    sig = az.analyze(AnalysisContext(session_id="t", intake_mode=Mode.FILE))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass


def test_constant_return_would_fail_discrimination():
    store = InMemoryPhashStore()
    store.add("p7", str(imagehash.phash(_to_pil(_document(7)), hash_size=16)))
    az = PhashResubmissionAnalyzer(store=store)
    hit = az.analyze(_ctx(_rescaled_then_blurred(_document(7)))).suspicion
    miss = az.analyze(_ctx(_document(999))).suspicion
    # A constant-returning fake would make these equal; the real detector separates them.
    assert hit != miss


# --- helpers -------------------------------------------------------------------------------------

def _to_pil(arr: np.ndarray):
    from PIL import Image

    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")


def _ctx(image: np.ndarray) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["rectified"] = image
    return ctx
