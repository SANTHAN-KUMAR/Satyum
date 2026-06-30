"""API-layer tests for POST /api/sources/{provider}/pull — the wired source-pull endpoint.

Proves the real route → provider registry → real verifier → audit path: a PAN structure pull, a
DigiLocker Path B verified pull that feeds the verification core (producing a source-verified
TrustScore), the 404 for an unknown provider, and the DPDP consent audit being recorded.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cryptography")
pytest.importorskip("pyhanko")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.registry_assembly import build_registry  # noqa: E402
from app.routes.sources import router as sources_router  # noqa: E402
from providers.registry import build_provider_registry  # noqa: E402
from risk.audit import AuditLedger  # noqa: E402
from tests.crypto_fixtures import make_ca, make_leaf, minimal_pdf, sign_pdf, write_anchor_dir  # noqa: E402


@pytest.fixture
def anchored_app(tmp_path):
    """An app whose provider + analyzer registries pin a throwaway test CA as the trust anchor."""
    ca_key, ca_cert = make_ca("Satyum CCA Test Root")
    anchor_dir = write_anchor_dir(tmp_path, ca_cert)

    app = FastAPI()
    app.state.ledger = AuditLedger()
    app.state.registry = build_registry(trust_anchor_dir=anchor_dir)
    app.state.providers = build_provider_registry(trust_anchor_dir=anchor_dir)
    app.include_router(sources_router)
    return app, (ca_key, ca_cert)


def _form(**overrides):
    base = {
        "doc_class": "identity",
        "consent_id": "c-123",
        "purpose": "loan_underwriting_document_verification",
    }
    base.update(overrides)
    return base


def test_pan_pull_returns_structure_and_no_trust_score(anchored_app):
    app, _ = anchored_app
    client = TestClient(app)
    resp = client.post(
        "/api/sources/pan/pull",
        data=_form(doc_class="identity", applicant_ref="ABCPK1234L"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_result"]["signature_status"] == "NOT_VERIFIED"
    assert body["source_result"]["measurements"]["pan_structure_valid"] is True
    assert body["trust_score"] is None  # a PAN check yields a fact, not a scored document


def test_digilocker_verified_pull_feeds_the_core(anchored_app):
    app, (ca_key, ca_cert) = anchored_app
    leaf_key, leaf_cert = make_leaf(ca_key, ca_cert, "NeGD DigiLocker Issuer")
    signed = sign_pdf(minimal_pdf(), leaf_key, leaf_cert, ca_cert)

    client = TestClient(app)
    resp = client.post(
        "/api/sources/digilocker/pull",
        data=_form(doc_class="financial_statement", issuer_hint="sbi"),
        files={"file": ("issued.pdf", signed, "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    sr = body["source_result"]
    assert sr["signature_status"] == "VERIFIED"
    assert sr["issuer"] == "NeGD DigiLocker Issuer"
    # Integrity answered at the root flows into the deterministic core -> a source-verified TrustScore.
    assert body["trust_score"] is not None
    assert body["trust_score"]["provenance"]["verified"] is True
    assert body["trust_score"]["tier_reached"] == "source-verified"


def test_digilocker_unsigned_pdf_is_absent_no_trust_score(anchored_app):
    app, _ = anchored_app
    client = TestClient(app)
    resp = client.post(
        "/api/sources/digilocker/pull",
        data=_form(doc_class="financial_statement"),
        files={"file": ("plain.pdf", minimal_pdf(), "application/pdf")},
    )
    body = resp.json()
    assert body["source_result"]["signature_status"] == "ABSENT"
    assert body["trust_score"] is None  # nothing verified at source -> no source-verified score


def test_unknown_provider_returns_404(anchored_app):
    app, _ = anchored_app
    client = TestClient(app)
    resp = client.post("/api/sources/nope/pull", data=_form())
    assert resp.status_code == 404


def test_bad_doc_class_returns_400(anchored_app):
    app, _ = anchored_app
    client = TestClient(app)
    resp = client.post("/api/sources/pan/pull", data=_form(doc_class="banana"))
    assert resp.status_code == 400


def test_consent_audit_is_recorded(anchored_app):
    app, _ = anchored_app
    client = TestClient(app)
    client.post("/api/sources/pan/pull", data=_form(consent_id="audit-me", applicant_ref="ABCPK1234L"))
    # The consent + outcome is in the tamper-evident ledger (DPDP §7.3), and the chain stays intact.
    ok, _broken = app.state.ledger.verify_chain()
    assert ok is True
    payloads = [r.payload for r in app.state.ledger.records()]
    assert any(p.get("event") == "source_pull" and p.get("consent_id") == "audit-me" for p in payloads)
