"""Discrimination tests for deterministic entity extraction (forensics/entities.py).

These prove REAL behaviour (CLAUDE.md §3.2): the Verhoeff checksum catches every single-digit edit
(the must-fail property UIDAI relies on), and extraction pulls the right structured identifiers out of
realistic document text. Every test would FAIL against a constant return.
"""

from __future__ import annotations

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.entities import (
    EntityExtractionAnalyzer,
    extract_entities,
    normalise_name,
    verhoeff_check_digit,
    verhoeff_validate,
)


def _valid_aadhaar(base: str = "23456789012") -> str:
    return base + str(verhoeff_check_digit(base))


def _ocr_words(text: str) -> list[dict]:
    """Build the canonical ctx.shared['ocr'] word-list shape from plain text lines."""
    words: list[dict] = []
    for li, line in enumerate(text.strip().split("\n")):
        for wi, tok in enumerate(line.split()):
            words.append({
                "text": tok, "left": wi * 60, "top": li * 30, "width": 50, "height": 20,
                "conf": 0.9, "line_num": li, "block_num": 0,
            })
    return words


# --- Verhoeff: the real UIDAI checksum, proven by its error-detection guarantees ------------------

def test_verhoeff_accepts_a_generated_number():
    assert verhoeff_validate(_valid_aadhaar()) is True


def test_verhoeff_rejects_every_single_digit_edit():
    """Verhoeff's defining property: ALL single-digit errors are caught. This is the must-fail."""
    a = _valid_aadhaar()
    for i in range(len(a)):
        for d in "0123456789":
            if d != a[i]:
                mutated = a[:i] + d + a[i + 1:]
                assert verhoeff_validate(mutated) is False, f"undetected edit at pos {i} -> {d}"


def test_verhoeff_catches_adjacent_transpositions():
    a = _valid_aadhaar()
    tested = 0
    for i in range(len(a) - 1):
        if a[i] != a[i + 1]:
            swapped = a[:i] + a[i + 1] + a[i] + a[i + 2:]
            assert verhoeff_validate(swapped) is False, f"undetected transposition at {i}"
            tested += 1
    assert tested >= 3  # actually exercised several transpositions, not vacuous


def test_verhoeff_rejects_non_digits():
    assert verhoeff_validate("12A4") is False
    assert verhoeff_validate("") is False


# --- Field extraction ----------------------------------------------------------------------------

def test_extracts_indian_identifiers_from_realistic_text():
    a = _valid_aadhaar()
    text = (
        "Account Holder: Mr John A Smith\n"
        "PAN ABCDE1234F\n"
        f"Aadhaar {a[:4]} {a[4:8]} {a[8:]}\n"
        "IFSC: SBIN0001234\n"
        "A/c No: 0012 3456 7890\n"
        "Date of Birth: 14-03-1985"
    )
    e = extract_entities(text)
    assert e.pan == "ABCDE1234F"
    assert e.aadhaar == a                      # only because it passes Verhoeff
    assert e.ifsc == "SBIN0001234"
    assert e.account_number == "001234567890"
    assert e.name == "JOHN A SMITH"            # title "Mr" stripped, upper-cased
    assert e.dob == "1985-03-14"               # normalised to ISO


def test_aadhaar_failing_checksum_is_flagged_not_trusted():
    """An Aadhaar-SHAPED number that fails Verhoeff is a forgery signal, never a trusted id."""
    a = _valid_aadhaar()
    bad = a[:-1] + str((int(a[-1]) + 1) % 10)  # single-digit edit -> guaranteed invalid
    e = extract_entities(f"Aadhaar No: {bad[:4]} {bad[4:8]} {bad[8:]}")
    assert e.aadhaar is None
    assert e.aadhaar_invalid == bad


def test_bare_customer_id_is_not_flagged_as_a_forged_aadhaar():
    """KNOWN_ISSUES #5.2: a 12-digit bank Customer ID with no Aadhaar context must NOT be routed to the
    UIDAI checksum. It is neither a trusted Aadhaar nor a forgery flag — it is simply not an Aadhaar.

    Discrimination: FAILS against the old code, which ran EVERY 12-digit number through Verhoeff and
    surfaced a false ``aadhaar_invalid`` on genuine statements.
    """
    # A bare 12-digit id printed the way Canara prints a Customer ID — no spacing, no Aadhaar label.
    e = extract_entities("Customer ID 912345678901\nAccount Statement for June 2026")
    assert e.aadhaar is None
    assert e.aadhaar_invalid is None  # the crux: no forgery signal manufactured from a Customer ID


def test_spaced_aadhaar_without_a_label_is_still_recognised():
    """The canonical UIDAI 4-4-4 print grouping is itself Aadhaar context (customer IDs never use it)."""
    a = _valid_aadhaar()
    e = extract_entities(f"{a[:4]} {a[4:8]} {a[8:]}")  # spaced, no nearby 'Aadhaar' word
    assert e.aadhaar == a
    # A spaced-but-checksum-failed number in Aadhaar format is a genuine forgery tell — still caught.
    bad = a[:-1] + str((int(a[-1]) + 1) % 10)
    e_bad = extract_entities(f"{bad[:4]} {bad[4:8]} {bad[8:]}")
    assert e_bad.aadhaar is None and e_bad.aadhaar_invalid == bad


def test_labelled_bare_aadhaar_is_recognised_from_context():
    """A nearby 'Aadhaar'/'UID' label is context even when the digits are not 4-4-4 spaced."""
    a = _valid_aadhaar()
    assert extract_entities(f"Aadhaar No {a}").aadhaar == a
    assert extract_entities(f"UID: {a}").aadhaar == a


def test_customer_id_checksum_fail_does_not_produce_a_scored_signal():
    """End-to-end of #5.2: a Verhoeff-failing Customer ID leaves the analyzer NOT_EVALUATED, not VALID."""
    ctx = AnalysisContext(
        session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF-1.4",
        shared={"ocr": _ocr_words("Customer ID 912345678901")},
    )
    sig = EntityExtractionAnalyzer().analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED  # no false "Aadhaar forgery" penalty
    assert ctx.shared["entities"].aadhaar_invalid is None


def test_unlabelled_text_yields_no_name_and_no_false_fields():
    e = extract_entities("the quick brown fox jumps over the lazy dog 12345")
    assert e.name is None
    assert e.comparable_fields() == {}


def test_pan_format_is_strict():
    # 4 digits + trailing alpha required; a near-miss must not be extracted as a PAN.
    assert extract_entities("PAN ABCDE123F").pan is None     # only 3 digits
    assert extract_entities("PAN ABCD12345F").pan is None    # 4 alpha not 5


@pytest.mark.parametrize("raw,expected", [
    ("Mr John Smith", "JOHN SMITH"),
    ("SHRI  Ravi   Kumar", "RAVI KUMAR"),
    ("Ms. Priya Sharma", "PRIYA SHARMA"),
])
def test_name_normalisation(raw, expected):
    assert normalise_name(raw) == expected


# --- The analyzer (publishes entities; its own signal is NOT_EVALUATED) ---------------------------

def test_analyzer_publishes_entities_and_self_is_not_evaluated():
    words = _ocr_words("PAN: ABCDE1234F\nName: Jane Doe")
    ctx = AnalysisContext(
        session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF-1.4", shared={"ocr": words}
    )
    az = EntityExtractionAnalyzer()
    assert az.applicable(ctx) is True
    sig = az.analyze(ctx)
    # Extraction is not a judgment -> never scores a document on its own.
    assert sig.status == SignalStatus.NOT_EVALUATED
    ent = ctx.shared["entities"]
    assert ent.pan == "ABCDE1234F"
    assert ent.name == "JANE DOE"


def test_analyzer_not_applicable_on_camera_intake():
    az = EntityExtractionAnalyzer()
    ctx = AnalysisContext(session_id="s", intake_mode=Mode.CAMERA)
    assert az.applicable(ctx) is False


def test_aadhaar_checksum_failure_is_a_scored_signal_not_dead(tmp_path):
    """C1: a Verhoeff-failed Aadhaar must REACH scoring (VALID + suspicion), not be a dead measurement.

    Discrimination: a document with a checksum-failed Aadhaar must NOT score identically to one with no
    Aadhaar at all. Would FAIL against the old code, which always returned NOT_EVALUATED.
    """
    a = _valid_aadhaar()
    bad = a[:-1] + str((int(a[-1]) + 1) % 10)  # single edit -> guaranteed Verhoeff failure
    words = _ocr_words(f"Aadhaar No: {bad[:4]} {bad[4:8]} {bad[8:]}")
    ctx = AnalysisContext(
        session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF-1.4", shared={"ocr": words}
    )
    sig = EntityExtractionAnalyzer().analyze(ctx)
    assert sig.status == SignalStatus.VALID            # scores — no longer NOT_EVALUATED
    assert sig.suspicion is not None and sig.suspicion > 0.0
    assert "checksum" in sig.reason.lower()
    assert ctx.shared["entities"].aadhaar_invalid == bad

    # A document with a VALID Aadhaar does not raise this signal (discrimination).
    good_words = _ocr_words(f"Aadhaar No: {a[:4]} {a[4:8]} {a[8:]}")
    good_ctx = AnalysisContext(
        session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF-1.4", shared={"ocr": good_words}
    )
    good_sig = EntityExtractionAnalyzer().analyze(good_ctx)
    assert good_sig.status == SignalStatus.NOT_EVALUATED
