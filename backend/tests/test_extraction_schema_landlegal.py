"""The VLM extraction contract exposes the land/legal SCALAR fields the new packs read (ADR-004 §5).

These guard the wiring, not the model: the legal/land scalar predicates and document types are present
in the forced tool schema, and ``parse_tool_input`` admits a legal extraction while still dropping an
unknown predicate (the §5.4 hostile-input boundary holds for the widened vocabulary too).
"""

from __future__ import annotations

from forensics.extraction.schema import (
    DOC_TYPES,
    FIELD_VALUE_TYPE,
    build_tool_schema,
    parse_tool_input,
)

_LEGAL_SCALARS = ("consideration", "consideration_in_words", "effective_date", "term", "end_date")
_LAND_SCALARS = ("execution_date", "registration_date", "registration_number", "survey_number")


def test_legal_and_land_scalar_predicates_are_in_the_schema():
    schema = build_tool_schema()
    enum = set(schema["properties"]["fields"]["items"]["properties"]["predicate"]["enum"])
    for p in _LEGAL_SCALARS + _LAND_SCALARS:
        assert p in enum and p in FIELD_VALUE_TYPE


def test_new_document_types_are_offered():
    for dt in ("LOAN_AGREEMENT", "SALE_AGREEMENT", "LEASE_AGREEMENT", "SALE_DEED"):
        assert dt in DOC_TYPES


def test_value_types_match_the_ontology_intent():
    assert FIELD_VALUE_TYPE["consideration"] == "Money"
    assert FIELD_VALUE_TYPE["consideration_in_words"] == "Text"
    assert FIELD_VALUE_TYPE["term"] == "Duration"
    assert FIELD_VALUE_TYPE["registration_date"] == "Date"


def test_parse_admits_legal_fields_but_drops_unknown_predicate():
    raw = {
        "doc_type": "LOAN_AGREEMENT",
        "primary_language": "en",
        "fields": [
            {"predicate": "consideration", "value": "500000",
             "bbox": [0.1, 0.1, 0.2, 0.05], "confidence": 0.9},
            {"predicate": "consideration_in_words", "value": "Rupees Five Lakh Only",
             "bbox": [0.1, 0.2, 0.4, 0.05], "confidence": 0.9},
            {"predicate": "totally_made_up", "value": "x",
             "bbox": [0.0, 0.0, 0.1, 0.1], "confidence": 0.9},
        ],
    }
    out = parse_tool_input(raw, model_id="test", prompt_hash="h")
    preds = {f.predicate for f in out.fields}
    assert "consideration" in preds and "consideration_in_words" in preds
    assert "totally_made_up" not in preds  # unknown predicate dropped at the boundary
    assert out.doc_type == "LOAN_AGREEMENT"
