"""API tests for the application-case routes: POST /api/cases, GET /api/cases/{id}.

Proves the endpoint opens a consented case and reports the accumulated cross-document corroboration,
which strengthens as consistent documents are added and flags a hard-identifier mismatch.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.case_store import CaseStore
from app.routes.cases import router as cases_router
from forensics.entities import ExtractedEntities

PAN = "AVMPK9131D"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.state.case_store = CaseStore()
    app.include_router(cases_router)
    return TestClient(app)


def test_create_case_then_get_empty(client: TestClient):
    resp = client.post("/api/cases", data={"applicant_ref": "ref-1", "consent_id": "c-1"})
    assert resp.status_code == 201
    case_id = resp.json()["case_id"]
    assert case_id.startswith("case_")

    got = client.get(f"/api/cases/{case_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["document_count"] == 0
    assert body["corroboration_status"] == "NOT_EVALUATED"  # nothing to cross-check yet


def test_case_corroboration_strengthens_and_flags_mismatch(client: TestClient):
    store: CaseStore = client.app.state.case_store  # type: ignore[attr-defined]
    case = store.create(applicant_ref="ref-2", consent_id="c-2", now="2026-06-30T00:00:00Z")
    store.add_document(case.case_id, label="pan", verdict="REVIEW", now="t",
                       entities=ExtractedEntities(pan=PAN, name="asha kumar"))

    one = client.get(f"/api/cases/{case.case_id}").json()
    assert one["corroboration_status"] == "NOT_EVALUATED"  # single document

    store.add_document(case.case_id, label="statement", verdict="REVIEW", now="t",
                       entities=ExtractedEntities(pan=PAN, name="asha kumar", account_number="123"))
    two = client.get(f"/api/cases/{case.case_id}").json()
    assert two["corroboration_status"] == "VALID"
    assert two["identity_consistent"] is True
    assert two["document_count"] == 2

    # a document that disagrees on the hard identifier flags fraud
    store.add_document(case.case_id, label="aadhaar", verdict="REVIEW", now="t",
                       entities=ExtractedEntities(pan="ZZZZZ0000Z", name="someone else"))
    three = client.get(f"/api/cases/{case.case_id}").json()
    assert "pan" in three["hard_mismatch_fields"]
    assert three["identity_consistent"] is False


def test_unknown_case_is_404(client: TestClient):
    assert client.get("/api/cases/case_does_not_exist").status_code == 404


def test_evidence_endpoint_returns_every_document_full_pack(client: TestClient):
    """GET /api/cases/{id}/evidence is what the case-level Underwriter Copilot reads to answer a
    question about ANY document in the case — it must return every document's FULL evidence pack,
    not just the identity+verdict summary that GET /api/cases/{id} intentionally stays limited to."""
    store: CaseStore = client.app.state.case_store  # type: ignore[attr-defined]
    case = store.create(applicant_ref="ref-3", consent_id="c-3", now="2026-06-30T00:00:00Z")
    pan_pack = {"session_id": "s1", "verdict": "APPROVED", "trust_score": 91, "signals": []}
    stmt_pack = {"session_id": "s2", "verdict": "REVIEW", "trust_score": 77, "signals": [{"name": "f"}]}
    store.add_document(case.case_id, label="pan", verdict="APPROVED", now="t",
                       entities=ExtractedEntities(pan=PAN), evidence_pack=pan_pack)
    store.add_document(case.case_id, label="bank_statement", verdict="REVIEW", now="t",
                       entities=ExtractedEntities(pan=PAN), evidence_pack=stmt_pack)

    resp = client.get(f"/api/cases/{case.case_id}/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == case.case_id
    assert len(body["documents"]) == 2
    by_label = {d["label"]: d for d in body["documents"]}
    assert by_label["pan"]["evidence_pack"] == pan_pack
    assert by_label["bank_statement"]["evidence_pack"] == stmt_pack


def test_evidence_endpoint_unknown_case_is_404(client: TestClient):
    assert client.get("/api/cases/case_does_not_exist/evidence").status_code == 404


def test_evidence_endpoint_survives_a_document_with_no_pack(client: TestClient):
    """A document added without an evidence_pack (e.g. pre-migration) must not break the endpoint."""
    store: CaseStore = client.app.state.case_store  # type: ignore[attr-defined]
    case = store.create(applicant_ref=None, consent_id=None, now="t")
    store.add_document(case.case_id, label="pan", verdict="REVIEW", now="t",
                       entities=ExtractedEntities(pan=PAN))
    body = client.get(f"/api/cases/{case.case_id}/evidence").json()
    assert body["documents"][0]["evidence_pack"] is None
