"""The persistent application-case file: the cross-document graph must STRENGTHEN as documents accrue.

These prove the discriminative behaviour of the accumulating case (CLAUDE.md §3.2): one document cannot
corroborate anything; a second consistent document corroborates; a third strengthens it further; and a
document that disagrees on a hard identifier flags identity fraud. A constant return could not satisfy
all four.
"""

from __future__ import annotations

from app.case_store import CaseStore, case_corroboration
from app.contracts import SignalStatus
from forensics.entities import ExtractedEntities

PAN = "AVMPK9131D"
NOW = "2026-06-30T00:00:00Z"


def _pan_doc() -> ExtractedEntities:
    return ExtractedEntities(pan=PAN, name="karnala vamsi krishna", dob="1981-05-25")


def _statement_doc() -> ExtractedEntities:
    return ExtractedEntities(pan=PAN, name="karnala vamsi krishna", account_number="1234567890")


def _form16_doc() -> ExtractedEntities:
    return ExtractedEntities(pan=PAN, name="karnala vamsi krishna")


def _mismatched_doc() -> ExtractedEntities:
    return ExtractedEntities(pan="ZZZZZ9999Z", name="someone else")  # a different PAN entirely


def _store_with(entities_list) -> object:
    store = CaseStore()
    case = store.create(applicant_ref="ref-1", consent_id="c-1", now=NOW)
    for i, ent in enumerate(entities_list):
        store.add_document(case.case_id, label=f"doc{i}", entities=ent, verdict="REVIEW", now=NOW)
    return store.get(case.case_id)


def test_single_document_cannot_corroborate():
    case = _store_with([_pan_doc()])
    sig = case_corroboration(case)
    assert sig.status == SignalStatus.NOT_EVALUATED  # nothing to cross-check yet
    assert sig.suspicion is None


def test_second_consistent_document_corroborates():
    case = _store_with([_pan_doc(), _statement_doc()])
    sig = case_corroboration(case)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion < 0.5  # agreement -> low suspicion
    assert "pan" in [c["field"] for c in sig.measurements["comparisons"]]
    assert not sig.measurements.get("hard_reject")


def test_graph_strengthens_as_documents_accrue():
    """More consistent documents => more comparisons corroborating the same identity."""
    two = case_corroboration(_store_with([_pan_doc(), _statement_doc()]))
    three = case_corroboration(_store_with([_pan_doc(), _statement_doc(), _form16_doc()]))
    assert three.measurements["documents"] > two.measurements["documents"]
    # the corroboration spans at least as many agreeing comparisons as before (never weaker)
    assert len(three.measurements["comparisons"]) >= len(two.measurements["comparisons"])
    assert not three.measurements.get("hard_reject")


def test_a_document_that_disagrees_on_a_hard_identifier_flags_fraud():
    case = _store_with([_pan_doc(), _statement_doc(), _mismatched_doc()])
    sig = case_corroboration(case)
    assert sig.status == SignalStatus.VALID
    assert sig.measurements.get("hard_reject") is True  # PAN differs across the applicant's own docs
    assert "pan" in sig.measurements["hard_mismatch_fields"]


def test_add_document_accumulates_and_unknown_case_raises():
    store = CaseStore()
    case = store.create(applicant_ref=None, consent_id=None, now=NOW)
    store.add_document(case.case_id, label="pan", entities=_pan_doc(), verdict="REVIEW", now=NOW)
    store.add_document(case.case_id, label="statement", entities=_statement_doc(), verdict="REVIEW", now=NOW)
    assert len(store.get(case.case_id).documents) == 2
    try:
        store.add_document("case_nonexistent", label="x", entities=_pan_doc(), verdict="REVIEW", now=NOW)
        raise AssertionError("adding to an unknown case must raise")
    except KeyError:
        pass
