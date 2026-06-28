"""Discrimination tests for the template-fingerprint detector.

The headline claim (BUILD-MANIFEST "Template fingerprinting"): with NO corpus the detector is honest
— it returns NOT_EVALUATED, never a fabricated pass. With a real multi-template corpus it identifies
the matching layout (low suspicion) and flags a structurally unfamiliar document (raised suspicion).
These fail against a constant: an empty corpus must NOT be VALID, a recognised doc must score 0 and an
unfamiliar doc > 0 — no constant satisfies all three. Templates are generated programmatically
(CLAUDE.md §3.2 / §8).
"""

from __future__ import annotations

import cv2
import numpy as np

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.template import (
    TemplateFingerprintAnalyzer,
    TemplateLibrary,
    match_template,
)


# --- programmatic template fixtures --------------------------------------------------------------

def _bank_template(seed: int, header: str) -> np.ndarray:
    """A distinctive structured document skeleton (header box, ruled rows, scattered cells)."""
    rng = np.random.default_rng(seed)
    img = np.full((500, 700), 255, np.uint8)
    cv2.rectangle(img, (20, 20), (680, 90), 0, 2)
    cv2.putText(img, header, (40, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2, cv2.LINE_AA)
    for i in range(8):
        cv2.line(img, (20, 120 + i * 40), (680, 120 + i * 40), 0, 1)
    for k in range(40):
        x = int(rng.integers(40, 640))
        y = int(rng.integers(130, 470))
        cv2.putText(img, "X" + str(k % 9), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1, cv2.LINE_AA)
    return img


def _alien_document() -> np.ndarray:
    """A structurally unrelated image (scattered blobs) — matches no bank template."""
    img = np.full((500, 700), 255, np.uint8)
    rng = np.random.default_rng(99)
    for _ in range(300):
        c = rng.integers(0, 700, 2)
        cv2.circle(img, (int(c[0]) % 700, int(c[1]) % 500), int(rng.integers(2, 8)), 0, -1)
    return img


def _ctx(image: np.ndarray) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["rectified"] = image
    return ctx


def _corpus() -> TemplateLibrary:
    lib = TemplateLibrary()
    lib.add_template("canara_v1", "Canara Bank", _bank_template(1, "CANARA BANK"))
    lib.add_template("hdfc_v1", "HDFC Bank", _bank_template(2, "HDFC BANK"))
    lib.add_template("sbi_v1", "State Bank of India", _bank_template(3, "SBI"))
    return lib


# --- the honest gate: empty corpus -> NOT_EVALUATED ----------------------------------------------

def test_empty_corpus_is_not_evaluated_not_a_fake_pass():
    az = TemplateFingerprintAnalyzer()  # default = empty library
    sig = az.analyze(_ctx(_bank_template(1, "CANARA BANK")))
    assert sig.status == SignalStatus.NOT_EVALUATED, "no corpus must gate honestly, never a pass"
    assert sig.suspicion is None
    assert sig.measurements.get("corpus_size") == 0


def test_pure_match_empty_corpus_is_not_evaluated():
    result = match_template(_bank_template(1, "CANARA BANK"), TemplateLibrary())
    assert result.evaluated is False
    assert result.best is None


# --- recognition with a real multi-template corpus -----------------------------------------------

def test_recognises_matching_template():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    # A re-encoded (mildly blurred) copy of the Canara template — the same document, resubmitted.
    query = cv2.GaussianBlur(_bank_template(1, "CANARA BANK"), (3, 3), 0)
    sig = az.analyze(_ctx(query))

    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0, "a recognised genuine template is not suspicious"
    assert sig.measurements["recognised"] is True
    assert sig.measurements["best_template"] == "canara_v1"


def test_unfamiliar_document_raises_suspicion():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    sig = az.analyze(_ctx(_alien_document()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion > 0.0
    assert sig.measurements["recognised"] is False


def test_analyzer_discriminates_recognised_vs_unfamiliar():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    recognised = az.analyze(_ctx(cv2.GaussianBlur(_bank_template(1, "CANARA BANK"), (3, 3), 0)))
    unfamiliar = az.analyze(_ctx(_alien_document()))
    # the discriminating property — the whole point:
    assert recognised.suspicion != unfamiliar.suspicion
    assert recognised.suspicion < unfamiliar.suspicion


def test_matched_template_published_to_shared():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    ctx = _ctx(cv2.GaussianBlur(_bank_template(1, "CANARA BANK"), (3, 3), 0))
    az.analyze(ctx)
    matched = ctx.shared.get("matched_template")
    assert isinstance(matched, dict) and matched["template_id"] == "canara_v1"


def test_match_ratio_separates_same_template_from_other_bank():
    # Same-template match must score a clearly higher ratio than a different bank's template.
    lib = _corpus()
    canara_query = cv2.GaussianBlur(_bank_template(1, "CANARA BANK"), (3, 3), 0)
    result = match_template(canara_query, lib)
    by_id = {m.template_id: m.match_ratio for m in result.scores}
    assert by_id["canara_v1"] > by_id["hdfc_v1"]
    assert by_id["canara_v1"] > by_id["sbi_v1"]


# --- contract / no-image gating ------------------------------------------------------------------

def test_not_evaluated_without_image_even_with_corpus():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    sig = az.analyze(AnalysisContext(session_id="t", intake_mode=Mode.FILE))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_mode_is_file():
    az = TemplateFingerprintAnalyzer()
    assert az.mode == Mode.FILE
    assert az.layer == 3
    assert az.order == 31


# --- the §3.2 constant-return litmus -------------------------------------------------------------

def test_constant_return_would_fail_discrimination():
    az = TemplateFingerprintAnalyzer(library=_corpus())
    recognised = az.analyze(_ctx(cv2.GaussianBlur(_bank_template(1, "CANARA BANK"), (3, 3), 0)))
    unfamiliar = az.analyze(_ctx(_alien_document()))
    empty = TemplateFingerprintAnalyzer().analyze(_ctx(_bank_template(1, "CANARA BANK")))
    # A constant LayerSignal could never produce all three of: VALID susp 0, VALID susp>0, NOT_EVALUATED.
    statuses = {recognised.status, unfamiliar.status, empty.status}
    assert statuses == {SignalStatus.VALID, SignalStatus.NOT_EVALUATED}
    assert recognised.suspicion != unfamiliar.suspicion
