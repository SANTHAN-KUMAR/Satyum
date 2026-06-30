"""API tests for the rule loop + the §10 demo beat 5 (mine → approve → fires explainably in /api/verify)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app


def _separable_dataset() -> list[dict]:
    """A dataset cleanly separated by ``risk_flag`` so the mined rule is predictable for the test."""
    cases = [{"features": {"risk_flag": 1, "loan_amount": 2_000_000}, "is_fraud": True} for _ in range(10)]
    cases += [{"features": {"risk_flag": 0, "loan_amount": 500_000}, "is_fraud": False} for _ in range(30)]
    return cases


def test_mine_approve_then_rule_fires_in_verify():
    client = TestClient(create_app())

    # 1) Mine candidate rules from labelled cases (the federated-mining PoC).
    mine = client.post("/api/rules/mine", json={"cases": _separable_dataset(), "threat_class": "demo_ring"})
    assert mine.status_code == 200
    candidates = mine.json()["candidates"]
    assert candidates, "the miner should surface at least one candidate"
    rule_id = candidates[0]["rule_id"]

    # 2) Before approval the rule is a CANDIDATE and does NOT fire.
    listed = {r["rule_id"]: r for r in client.get("/api/rules").json()["rules"]}
    assert listed[rule_id]["status"] == "CANDIDATE"

    # 3) Analyst approves -> it deploys as a deterministic rule (and the approval is hash-chained).
    approve = client.post(f"/api/rules/{rule_id}/approve", json={"approved_by": "A. Rao"})
    assert approve.status_code == 200 and approve.json()["rule"]["status"] == "APPROVED"

    # 4) A new verification with matching features -> the promoted rule fires as a real signal.
    resp = client.post(
        "/api/verify",
        data={"features_json": json.dumps({"risk_flag": 1, "loan_amount": 2_000_000})},
        files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )
    assert resp.status_code == 200
    signals = {s["name"]: s for s in resp.json()["signals"]}
    promoted = signals["promoted_rules"]
    assert promoted["status"] == "VALID" and promoted["suspicion"] > 0
    # Explainable + admissible: the reason names the rule id and the approver.
    assert rule_id in promoted["reason"] and "A. Rao" in promoted["reason"]


def test_rule_does_not_fire_before_approval():
    client = TestClient(create_app())
    mine = client.post("/api/rules/mine", json={"cases": _separable_dataset()})
    # NOT approved -> not deployed -> promoted_rules is NOT_EVALUATED even with matching features.
    resp = client.post(
        "/api/verify",
        data={"features_json": json.dumps({"risk_flag": 1, "loan_amount": 2_000_000})},
        files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )
    signals = {s["name"]: s for s in resp.json()["signals"]}
    # No rule deployed -> the analyzer is not applicable -> skipped entirely (no signal emitted).
    assert "promoted_rules" not in signals


def test_reject_rule():
    client = TestClient(create_app())
    rule_id = client.post("/api/rules/mine", json={"cases": _separable_dataset()}).json()["candidates"][0]["rule_id"]
    r = client.post(f"/api/rules/{rule_id}/reject", json={"approved_by": "A. Rao"})
    assert r.status_code == 200 and r.json()["rule"]["status"] == "REJECTED"


def test_approve_unknown_rule_404():
    client = TestClient(create_app())
    assert client.post("/api/rules/NOPE/approve", json={"approved_by": "x"}).status_code == 404


def test_mining_persists_and_is_listed():
    client = TestClient(create_app())
    client.post("/api/rules/mine", json={"cases": _separable_dataset()})
    rules = client.get("/api/rules").json()["rules"]
    assert len(rules) >= 1
    assert all("confidence" in r and "provenance" in r for r in rules)
