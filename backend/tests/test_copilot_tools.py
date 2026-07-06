"""Discrimination tests for the case-aware Copilot tools (interpretability/tools.py).

The Underwriter Copilot must be able to answer a question about ANY document in an accumulating case,
not just the single most-recently-viewed one — but it must never silently answer about the WRONG
document when more than one is in scope. These tests prove the document-resolution logic for real
(CLAUDE.md §3.2): a single document in scope resolves with no argument; a named document resolves by
exact or case-insensitive label; an unnamed document with multiple candidates in scope is refused
(never guesses); and each tool's result is correctly scoped to the resolved document, never leaking
another document's data.
"""

from __future__ import annotations

import json

from interpretability.tools import (
    _resolve_document,
    execute_tool,
    get_evidence_regions,
    get_overall_verdict,
    get_signal_detail,
    list_case_documents,
)

PAN_PACK = {
    "verdict": "APPROVED",
    "trust_score": 91,
    "signals": [{"name": "claimed_identity", "reason": "matches"}],
    "tamper_evidence_regions": [],
}
STATEMENT_PACK = {
    "verdict": "REVIEW",
    "trust_score": 77,
    "signals": [{"name": "financial_consistency", "reason": "date order broke at row 31"}],
    "tamper_evidence_regions": [{"page": 0, "bbox": [0.1, 0.1, 0.2, 0.02]}],
}


# --- pure resolution logic --------------------------------------------------------------------------


def test_single_document_resolves_with_no_argument():
    docs = {"bank_statement.pdf": STATEMENT_PACK}
    pack, label, error = _resolve_document(docs, None)
    assert error is None
    assert label == "bank_statement.pdf"
    assert pack == STATEMENT_PACK


def test_multiple_documents_without_a_name_is_refused_not_guessed():
    """MUST-FAIL FIXTURE: with 2+ documents in scope and no 'document' argument, the resolver must
    refuse rather than silently pick one — a wrong silent pick would answer about the wrong document.
    Would FAIL (would return some pack) against a naive 'just take the first one' implementation."""
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    pack, label, error = _resolve_document(docs, None)
    assert pack is None and label is None
    assert error is not None and "more than one document" in error


def test_named_document_resolves_by_exact_label():
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    pack, label, error = _resolve_document(docs, "bank_statement.pdf")
    assert error is None
    assert label == "bank_statement.pdf"
    assert pack == STATEMENT_PACK


def test_named_document_resolves_case_insensitively():
    docs = {"Bank_Statement.pdf": STATEMENT_PACK}
    pack, label, error = _resolve_document(docs, "bank_statement.pdf")
    assert error is None and pack == STATEMENT_PACK


def test_unknown_document_name_is_refused_with_a_helpful_error():
    docs = {"pan.pdf": PAN_PACK}
    pack, label, error = _resolve_document(docs, "form16.pdf")
    assert pack is None and label is None
    assert error is not None and "form16.pdf" in error


def test_no_documents_in_scope_is_refused():
    pack, label, error = _resolve_document({}, None)
    assert pack is None and error is not None


# --- execute_tool: real per-document scoping, never leaking the other document's data --------------


def test_get_signal_detail_scoped_to_the_named_document():
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    out = json.loads(execute_tool(
        "get_signal_detail", {"document": "bank_statement.pdf", "signal_name": "financial_consistency"},
        docs,
    ))
    assert out["document"] == "bank_statement.pdf"
    assert "date order broke" in out["result"]["reason"]


def test_get_signal_detail_does_not_leak_the_other_document_signal():
    """A signal name that exists on document A but not document B must not be found via B."""
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    out = json.loads(execute_tool(
        "get_signal_detail", {"document": "pan.pdf", "signal_name": "financial_consistency"}, docs,
    ))
    assert "error" in out["result"]


def test_ambiguous_call_with_multiple_documents_returns_an_error_envelope():
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    out = json.loads(execute_tool("get_overall_verdict", {}, docs))
    assert "error" in out
    assert "more than one document" in out["error"]


def test_single_document_scope_needs_no_document_argument():
    docs = {"bank_statement.pdf": STATEMENT_PACK}
    out = json.loads(execute_tool("get_overall_verdict", {}, docs))
    assert out["document"] == "bank_statement.pdf"
    assert out["result"]["verdict"] == "REVIEW"


def test_list_case_documents_enumerates_every_document_with_its_verdict():
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    out = json.loads(execute_tool("list_case_documents", {}, docs))
    by_label = {d["document"]: d for d in out}
    assert by_label["pan.pdf"]["verdict"] == "APPROVED"
    assert by_label["bank_statement.pdf"]["verdict"] == "REVIEW"


def test_evidence_regions_are_scoped_per_document():
    docs = {"pan.pdf": PAN_PACK, "bank_statement.pdf": STATEMENT_PACK}
    empty = json.loads(execute_tool("get_evidence_regions", {"document": "pan.pdf"}, docs))
    flagged = json.loads(execute_tool("get_evidence_regions", {"document": "bank_statement.pdf"}, docs))
    assert empty["result"] == []
    assert len(flagged["result"]) == 1


def test_unknown_tool_name_is_an_error_not_a_crash():
    docs = {"pan.pdf": PAN_PACK}
    out = json.loads(execute_tool("delete_everything", {}, docs))
    assert "error" in out


# --- the underlying pure getters still work directly on one pack (back-compat sanity) ---------------


def test_pure_getters_operate_on_one_pack_directly():
    assert get_overall_verdict(STATEMENT_PACK)["verdict"] == "REVIEW"
    assert get_signal_detail(PAN_PACK, "claimed_identity")["reason"] == "matches"
    assert get_evidence_regions(STATEMENT_PACK) == STATEMENT_PACK["tamper_evidence_regions"]
    assert list_case_documents({"pan.pdf": PAN_PACK}) == [
        {"document": "pan.pdf", "verdict": "APPROVED", "trust_score": 91}
    ]
