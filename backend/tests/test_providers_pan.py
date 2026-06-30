"""Discrimination tests for the PAN provider — real offline structure validation (PROPOSAL-001 §4.4).

The honest claim (CLAUDE.md §3.1): structure + holder-type code are validated offline; the 10th-char
check digit is NOT (NSDL algorithm non-public), and existence/name-match is gated. These tests prove
the structure check actually discriminates and that the provider never fabricates a "verified".
"""

from __future__ import annotations

from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    SignatureStatus,
)
from providers.pan import PAN_ENTITY_CODES, PanProvider, validate_pan_structure


def _consent() -> ConsentArtifact:
    return ConsentArtifact(
        consent_id="c-1", purpose="loan_underwriting_document_verification",
        doc_class=DocClass.IDENTITY, granted_at="2026-06-30T00:00:00Z",
    )


def _req(pan: str | None) -> DocRequest:
    return DocRequest(doc_class=DocClass.IDENTITY, applicant_ref=pan)


# --- structure validator: genuine vs malformed (would FAIL against any constant) ------------------

def test_well_formed_individual_pan_is_structurally_valid():
    ok, entity, detail = validate_pan_structure("ABCPK1234L")  # 4th char 'P' = Individual
    assert ok is True
    assert entity == "Individual"
    assert "Individual" in detail


def test_each_entity_code_decodes():
    # Every documented holder-type code must decode (a real lookup, not a constant).
    # PAN = 5 letters + 4 digits + 1 letter; the 4th letter is the holder-type code.
    for code, expected in PAN_ENTITY_CODES.items():
        pan = f"ABC{code}Z1234L"  # ABC + code + Z = 5 letters, 1234 = 4 digits, L = check letter
        assert len(pan) == 10
        ok, entity, _ = validate_pan_structure(pan)
        assert ok is True and entity == expected, f"{code} -> {entity!r}"


def test_malformed_pan_fails_structure():
    # Wrong lengths / wrong character classes — each must fail (discrimination, not a constant).
    for bad in ["", "ABCDE1234", "ABCDE12345", "1BCPK1234L", "ABCPK1234", "ABCPKL234L", "ABCP01234L"]:
        ok, entity, _ = validate_pan_structure(bad)
        assert ok is False and entity is None, f"{bad!r} should be structurally invalid"


def test_invalid_holder_type_char_fails():
    # 'Z' is not a valid PAN holder-type code -> structurally invalid even though the shape matches.
    ok, entity, detail = validate_pan_structure("ABCZK1234L")
    assert ok is False and entity is None
    assert "holder-type" in detail


def test_genuine_and_malformed_are_separated():
    """The §3.2 litmus: no constant return satisfies both a valid and an invalid PAN."""
    good, _, _ = validate_pan_structure("ABCPK1234L")
    bad, _, _ = validate_pan_structure("NOTAPAN")
    assert good is True and bad is False


# --- provider: never fabricates VERIFIED; gates existence honestly --------------------------------

def test_provider_reports_structure_and_gates_existence():
    res = PanProvider().fetch(_consent(), _req("ABCPK1234L"))
    # A PAN is not a signed artifact: never VERIFIED, always a precise gate for true existence.
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.verified_at_source is False
    assert res.gate and "Protean" in res.gate
    assert res.measurements["pan_structure_valid"] is True
    assert res.measurements["entity_type"] == "Individual"
    # We must NOT claim a checksum we cannot compute (§3.1).
    assert "NOT validated" in res.measurements["checksum_note"]


def test_provider_flags_malformed_pan_structure():
    res = PanProvider().fetch(_consent(), _req("NOTAPAN"))
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.measurements["pan_structure_valid"] is False
    assert res.issuer is None  # no issuer asserted for a structurally invalid PAN


def test_provider_applicable_only_for_identity():
    p = PanProvider()
    assert p.applicable(DocRequest(doc_class=DocClass.IDENTITY)) is True
    assert p.applicable(DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT)) is False
