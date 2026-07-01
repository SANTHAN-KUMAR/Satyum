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
