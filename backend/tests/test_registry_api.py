"""API tests for the fraud-registry endpoints and the automatic consult during /api/verify."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode
from app.registry import AnalyzerRegistry
from app.routes.registry import router as registry_router
from app.routes.verify import router as verify_router
from federation.registry import FraudRegistry
from federation.service import report_fraud
from forensics.entities import ExtractedEntities
from risk.audit import AuditLedger
from app.session import SessionManager

_PHASH = "f0e1d2c3b4a5968778695a4b3c2d1e0f0123456789abcdef0123456789abcdef"


def _registry_app() -> FastAPI:
    app = FastAPI()
    app.state.fraud_registry = FraudRegistry()
    app.include_router(registry_router)
    return app


def test_report_then_query_matches():
    client = TestClient(_registry_app())
    r = client.post("/api/registry/report", data={
        "threat_class": "forged_statement", "label": "bankA:LN-1", "phash_hex": _PHASH,
        "pan": "ABCPK1234L", "bank_id": "bankA",
    })
    assert r.status_code == 200 and r.json()["reported"] is True

    # Same PAN reused (different/no document) -> entity-reuse hit.
    q = client.post("/api/registry/query", data={"pan": "ABCPK1234L"})
    body = q.json()
    assert body["matched"] is True
    assert body["matches"][0]["label"] == "bankA:LN-1"
    assert "pan" in body["matches"][0]["matched_token_kinds"]


def test_query_no_match_is_empty():
    client = TestClient(_registry_app())
    client.post("/api/registry/report", data={
        "threat_class": "forged_statement", "label": "a", "pan": "ABCPK1234L"})
    q = client.post("/api/registry/query", data={"pan": "ZZZPZ9999Z"})
    assert q.json()["matched"] is False


# --- the automatic consult during /api/verify (a custom analyzer publishes the pHash) -------------

class _PublishPhash:
    """Test analyzer that publishes a known pHash into ctx.shared, as the real pHash analyzer does."""

    name = "publish_phash"
    layer = 3
    mode = Mode.ANY

    def __init__(self, phash_hex: str) -> None:
        self._phash = phash_hex

    def applicable(self, ctx: AnalysisContext) -> bool:
        return True

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        ctx.shared["phash_hex"] = self._phash
        return LayerSignal.not_evaluated(self.name, self.layer, self.mode, "published pHash (test)")


def _verify_app_with_registry(phash_hex: str) -> FastAPI:
    app = FastAPI()
    reg = AnalyzerRegistry()
    reg.register(_PublishPhash(phash_hex))
    app.state.registry = reg
    app.state.ledger = AuditLedger()
    app.state.sessions = SessionManager()
    app.state.fraud_registry = FraudRegistry()
    app.include_router(verify_router)
    return app


def test_verify_route_attaches_registry_advisory_on_match():
    app = _verify_app_with_registry(_PHASH)
    # A prior confirmed fraud at "Bank A" with this exact pHash.
    report_fraud(
        app.state.fraud_registry, phash_hex=_PHASH, entities=None,
        threat_class="forged_statement", label="bankA:LN-1", bank_id="bankA",
        timestamp="2026-06-18T00:00:00Z",
        salt_hex=settings.federation_consortium_salt_hex,
        pepper=settings.federation_entity_pepper.encode("utf-8"),
    )
    client = TestClient(app)
    resp = client.post("/api/verify", files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")})
    assert resp.status_code == 200
    body = resp.json()
    ni = body["evidence_pack"]["network_intelligence"]
    assert len(ni) == 1
    assert ni[0]["source"] == "fraud_registry"
    assert "not a verdict" in ni[0]["note"]
    # The advisory was attached as a labelled audit line and the chain stays intact.
    ok, _ = app.state.ledger.verify_chain()
    assert ok is True


def test_verify_route_no_registry_match_is_unchanged():
    app = _verify_app_with_registry(_PHASH)  # registry empty -> no match
    client = TestClient(app)
    resp = client.post("/api/verify", files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")})
    body = resp.json()
    assert body["evidence_pack"]["network_intelligence"] == []  # fail-open: no finding
