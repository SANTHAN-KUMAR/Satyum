"""API tests for the cross-bank ring-detection endpoints (the §10 demo beat 4)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.ring import router as ring_router
from federation.graph import EntityGraph


def _ring_app() -> TestClient:
    app = FastAPI()
    app.state.entity_graph = EntityGraph()
    app.include_router(ring_router)
    return TestClient(app)


def test_five_banks_pooled_reveal_a_ring():
    client = _ring_app()
    shared = {"payout_account": "50100123456789", "device": "DV-FP-AA11", "employer": "COMPANY X"}
    for case_id, bank in [("canara:1", "canara"), ("sbi:2", "sbi"), ("hdfc:3", "hdfc"),
                          ("icici:4", "icici"), ("union:5", "union")]:
        r = client.post("/api/ring/application", data={"case_id": case_id, "bank_id": bank, **shared})
        assert r.status_code == 200

    detect = client.post("/api/ring/detect").json()
    assert detect["ring_count"] == 1
    ring = detect["rings"][0]
    assert len(ring["members"]) == 5 and len(ring["banks"]) == 5
    assert set(ring["shared_identifiers"]) == {"payout_account", "device", "employer"}

    # The per-case panel returns the ring as a finding (not a verdict).
    case = client.get("/api/ring/case/canara:1").json()
    assert case["in_ring"] is True
    assert case["findings"][0]["source"] == "ring_evidence"
    assert case["findings"][0]["note"] == "finding — not a verdict"


def test_unrelated_applications_have_no_ring():
    client = _ring_app()
    for i in range(3):
        client.post("/api/ring/application",
                    data={"case_id": f"x:{i}", "bank_id": "b", "payout_account": f"acct-{i}"})
    assert client.post("/api/ring/detect").json()["ring_count"] == 0
    assert client.get("/api/ring/case/x:0").json()["in_ring"] is False


def test_raw_identifiers_are_tokenised_not_stored(monkeypatch):
    """White-box: the graph node must hold an HMAC token, never the raw payout account."""
    client = _ring_app()
    client.post("/api/ring/application",
                data={"case_id": "c:1", "bank_id": "b", "payout_account": "50100999888777"})
    graph: EntityGraph = client.app.state.entity_graph
    node = graph._nodes["c:1"]  # noqa: SLF001
    assert "50100999888777" not in node.linkage_tokens["payout_account"]
