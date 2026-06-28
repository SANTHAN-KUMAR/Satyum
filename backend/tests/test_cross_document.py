"""Discrimination tests for the cross-document consistency graph (forensics/cross_document.py).

Proves the bundle-level claim (ADR-003 #3): a consistent bundle corroborates (low suspicion), a
hard-identifier mismatch is near-dispositive, a name-only mismatch is medium, legitimate name variance
does NOT false-positive, and an un-comparable bundle is honestly NOT_EVALUATED — never a fake pass.
Each would FAIL against a constant return.
"""

from __future__ import annotations

import pytest

from app.contracts import SignalStatus
from forensics.cross_document import cross_document_signal
from forensics.entities import ExtractedEntities


def test_consistent_bundle_corroborates_with_low_suspicion():
    a = ExtractedEntities(pan="ABCDE1234F", name="JOHN SMITH", dob="1985-03-14")
    b = ExtractedEntities(pan="ABCDE1234F", name="JOHN A SMITH", dob="1985-03-14")
    sig = cross_document_signal({"stmt": a, "id": b})
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion < 0.1
    assert sig.measurements["disagreeing_fields"] == []
    assert "consistent" in sig.reason.lower()


def test_pan_mismatch_is_high_suspicion_and_names_the_field_and_docs():
    a = ExtractedEntities(pan="ABCDE1234F", name="JOHN SMITH")
    b = ExtractedEntities(pan="ZZZZZ9999Z", name="JOHN SMITH")
    sig = cross_document_signal({"bank_statement": a, "id_card": b})
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion >= 0.9
    assert "pan" in sig.measurements["disagreeing_fields"]
    assert "MISMATCH" in sig.reason
    # The evidence names BOTH documents and BOTH values (explainability, §9).
    assert "bank_statement" in sig.reason and "id_card" in sig.reason
    assert "ABCDE1234F" in sig.reason and "ZZZZZ9999Z" in sig.reason


def test_name_only_mismatch_is_clamped_to_review_band_not_reject():
    # H2: names are a SOFT corroborator (transliteration/typo variance). A name-only disagreement must
    # NOT hard-reject a genuine applicant — it lands in the REVIEW band so a human checks.
    a = ExtractedEntities(name="JOHN SMITH")
    b = ExtractedEntities(name="RAVI KUMAR")
    sig = cross_document_signal({"a": a, "b": b})
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and 0.35 <= sig.suspicion <= 0.45  # REVIEW band, never 0.60+
    assert sig.measurements["disagreeing_fields"] == ["name"]
    assert sig.measurements["hard_mismatch_fields"] == []  # a name alone is never dispositive


def test_single_char_ocr_slip_in_pan_is_near_match_review_not_reject():
    # H1: ABCDE1234F vs ABCOE1234F (a single D->O OCR misread on a genuine PAN). Must be a NEAR match
    # (possible OCR misread -> REVIEW band), NOT a 0.92 hard reject of a real applicant.
    sig = cross_document_signal({
        "stmt": ExtractedEntities(pan="ABCDE1234F"),
        "id": ExtractedEntities(pan="ABCOE1234F"),
    })
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion <= 0.41  # REVIEW band
    assert sig.measurements["near_match_fields"] == ["pan"]
    assert sig.measurements["hard_mismatch_fields"] == []  # not a dispositive fraud claim


def test_far_apart_pan_stays_a_hard_mismatch():
    # The OCR tolerance must NOT swallow a real forgery: values many chars apart stay dispositive.
    sig = cross_document_signal({
        "stmt": ExtractedEntities(pan="ABCDE1234F"),
        "id": ExtractedEntities(pan="ZZZZZ9999Z"),
    })
    assert sig.suspicion is not None and sig.suspicion >= 0.9
    assert sig.measurements["hard_mismatch_fields"] == ["pan"]


@pytest.mark.parametrize("n1,n2", [
    ("A KUMAR", "B KUMAR"),       # different initials, same surname -> DIFFERENT people
    ("JOHN", "JOHN SMITH"),       # first-name-only vs full -> surname differs
    ("RAVI KUMAR", "MOHAN LAL"),  # clearly different
])
def test_name_matcher_does_not_false_positive_on_different_people(n1, n2):
    # M3 (fail-OPEN guard): a bare similarity ratio wrongly accepted "A KUMAR" ~ "B KUMAR". The
    # surname-anchored matcher must flag these as a name disagreement, not "consistent".
    sig = cross_document_signal({"a": ExtractedEntities(name=n1), "b": ExtractedEntities(name=n2)})
    assert "name" in sig.measurements["disagreeing_fields"], (n1, n2)


@pytest.mark.parametrize("n1,n2", [
    ("JOHN SMITH", "J SMITH"),        # initial vs full first name
    ("JOHN A SMITH", "JOHN SMITH"),   # missing middle name
    ("RAVI KUMAR", "RAVI  KUMAR"),    # whitespace
    ("PRIYA SHARMA", "PRIYA SHARNA"), # single typo -> high ratio
])
def test_legitimate_name_variants_do_not_false_positive(n1, n2):
    sig = cross_document_signal({"a": ExtractedEntities(name=n1), "b": ExtractedEntities(name=n2)})
    assert sig.measurements["disagreeing_fields"] == [], (n1, n2)
    assert sig.suspicion is not None and sig.suspicion < 0.1


def test_no_overlapping_field_is_not_evaluated_not_a_fake_pass():
    # Each doc carries a DIFFERENT field -> nothing to cross-check -> honest NOT_EVALUATED.
    a = ExtractedEntities(pan="ABCDE1234F")
    b = ExtractedEntities(ifsc="SBIN0001234")
    sig = cross_document_signal({"a": a, "b": b})
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_single_document_is_not_evaluated():
    sig = cross_document_signal({"only": ExtractedEntities(pan="ABCDE1234F")})
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_discriminates_consistent_from_mismatched_constant_guard():
    """The same code path must yield DIFFERENT suspicion for agree vs mismatch (no constant return)."""
    consistent = cross_document_signal({
        "a": ExtractedEntities(pan="ABCDE1234F", name="ASHA RAO"),
        "b": ExtractedEntities(pan="ABCDE1234F", name="ASHA RAO"),
    })
    mismatch = cross_document_signal({
        "a": ExtractedEntities(pan="ABCDE1234F", name="ASHA RAO"),
        "b": ExtractedEntities(pan="ZZZZZ9999Z", name="ASHA RAO"),  # hard PAN mismatch
    })
    assert consistent.suspicion is not None and mismatch.suspicion is not None
    assert mismatch.suspicion > consistent.suspicion + 0.4


def test_hard_identifier_mismatch_outranks_name_agreement():
    # Names agree but the account numbers differ -> the hard-identifier mismatch must dominate.
    a = ExtractedEntities(name="JOHN SMITH", account_number="111111111111")
    b = ExtractedEntities(name="JOHN SMITH", account_number="999999999999")
    sig = cross_document_signal({"a": a, "b": b})
    assert sig.suspicion is not None and sig.suspicion >= 0.8
    assert "account_number" in sig.measurements["disagreeing_fields"]
