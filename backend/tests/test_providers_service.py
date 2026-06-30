"""Tests for the provider registry + source-pull service (selection, fail-closed, consent scope)."""

from __future__ import annotations

import pytest

from providers.contracts import ConsentArtifact, DocClass, DocRequest, SignatureStatus
from providers.registry import ProviderRegistry, build_provider_registry
from providers.service import UnknownProviderError, pull_source


def _consent(doc_class: DocClass = DocClass.IDENTITY) -> ConsentArtifact:
    return ConsentArtifact(
        consent_id="c", purpose="loan_underwriting_document_verification",
        doc_class=doc_class, granted_at="2026-06-30T00:00:00Z",
    )


def test_registry_wires_all_providers():
    reg = build_provider_registry()
    names = {p.name for p in reg.all()}
    assert names == {"digilocker", "account_aggregator", "aadhaar_offline", "pan"}


def test_registry_rejects_duplicate_names():
    reg = ProviderRegistry()
    from providers.pan import PanProvider
    reg.register(PanProvider())
    with pytest.raises(ValueError):
        reg.register(PanProvider())


def test_applicable_selects_by_doc_class():
    reg = build_provider_registry()
    # Identity -> digilocker + pan (both applicable); financial -> digilocker + account_aggregator.
    id_providers = {p.name for p in reg.applicable(DocRequest(doc_class=DocClass.IDENTITY))}
    fin_providers = {p.name for p in reg.applicable(DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT))}
    assert "pan" in id_providers and "account_aggregator" not in id_providers
    assert "account_aggregator" in fin_providers and "pan" not in fin_providers


def test_unknown_provider_raises():
    reg = build_provider_registry()
    with pytest.raises(UnknownProviderError):
        pull_source(reg, "nonexistent", _consent(), DocRequest(doc_class=DocClass.IDENTITY))


def test_consent_scope_mismatch_is_refused_fail_closed():
    """A consent record bound to IDENTITY must not authorise a FINANCIAL_STATEMENT pull (DPDP §7.3)."""
    reg = build_provider_registry()
    res = pull_source(
        reg, "account_aggregator",
        _consent(DocClass.IDENTITY),                       # consent scope = identity
        DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT),  # request = financial
    )
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert "purpose limitation" in res.detail.lower()


def test_pan_pull_through_service_returns_structure_result():
    reg = build_provider_registry()
    res = pull_source(
        reg, "pan", _consent(DocClass.IDENTITY),
        DocRequest(doc_class=DocClass.IDENTITY, applicant_ref="ABCPK1234L"),
    )
    assert res.provider == "pan"
    assert res.measurements["pan_structure_valid"] is True
