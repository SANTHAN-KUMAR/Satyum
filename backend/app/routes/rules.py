"""The rule-discovery loop API (PROPOSAL-001 §6.3.1) — mine, review, approve/reject.

  * ``POST /api/rules/mine``         — run the federated rule-mining PoC on labelled cases → candidates.
  * ``GET  /api/rules``              — list every rule with its measured metrics + review status.
  * ``POST /api/rules/{id}/approve`` — analyst approves → the rule deploys as a deterministic L2 rule
                                       (fires live in /api/verify) and the approval is hash-chained.
  * ``POST /api/rules/{id}/reject``  — analyst rejects → logged, never deployed.

The miner is an honest single-round PoC (real measured metrics, never invented). Approval is the human
gate that makes an FL finding *admissible* — every future firing cites the rule id + the approver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from rule_mining.miner import LabeledCase, mine_rules
from rule_mining.model import RuleRecord
from rule_mining.store import RuleNotFoundError

log = structlog.get_logger(__name__)

router = APIRouter()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


class LabeledCaseIn(BaseModel):
    features: dict[str, Any]
    is_fraud: bool


class MineRequest(BaseModel):
    cases: list[LabeledCaseIn] = Field(min_length=1)
    threat_class: str = "mined_pattern"
    min_support: float = 0.10
    min_confidence: float = 0.80
    max_predicates: int = 3
    top_k: int = 10
    round_label: str = "poc-r1"


class DecisionRequest(BaseModel):
    approved_by: str


def _rule_dto(record: RuleRecord) -> dict[str, Any]:
    r = record.rule
    return {
        "rule_id": r.rule_id,
        "predicates": r.describe(),
        "predicate_list": [{"feature": p.feature, "op": p.op, "value": p.value} for p in r.predicates],
        "threat_class": r.threat_class,
        "suspicion": r.suspicion,
        "support": r.support,
        "confidence": r.confidence,
        "lift": r.lift,
        "provenance": r.provenance,
        "status": record.status.value,
        "approved_by": record.approved_by,
        "decided_at": record.decided_at,
    }


@router.post("/api/rules/mine")
async def mine_route(request: Request, body: MineRequest) -> dict[str, Any]:
    """Mine candidate rules from labelled cases (PoC) and store them as CANDIDATEs for review."""
    store = request.app.state.rule_store
    cases = [LabeledCase(features=c.features, is_fraud=c.is_fraud) for c in body.cases]
    rules = mine_rules(
        cases, threat_class=body.threat_class, min_support=body.min_support,
        min_confidence=body.min_confidence, max_predicates=body.max_predicates,
        top_k=body.top_k, round_label=body.round_label,
    )
    records = store.add_candidates(rules)
    log.info("rules.mined", count=len(records), cases=len(cases),
             fraud=sum(c.is_fraud for c in cases))
    return {"mined": len(records), "candidates": [_rule_dto(r) for r in records]}


@router.get("/api/rules")
async def list_rules(request: Request) -> dict[str, Any]:
    store = request.app.state.rule_store
    return {"rules": [_rule_dto(r) for r in store.all()]}


@router.post("/api/rules/{rule_id}/approve")
async def approve_route(request: Request, rule_id: str, body: DecisionRequest) -> dict[str, Any]:
    """Approve a candidate -> deploy it as a deterministic rule, and hash-chain the approval."""
    store = request.app.state.rule_store
    ledger = request.app.state.ledger
    try:
        record = store.approve(rule_id, approved_by=body.approved_by, decided_at=_iso_now())
    except RuleNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown rule {rule_id!r}"
        ) from None
    # Auditable, hash-chained rule-promotion record (§6.3.1) — the rule is now admissible evidence.
    ledger.record(_iso_now(), {
        "event": "rule_approved", "rule_id": rule_id, "approved_by": body.approved_by,
        "decided_at": record.decided_at, "predicates": record.rule.describe(),
        "confidence": record.rule.confidence, "support": record.rule.support,
        "threat_class": record.rule.threat_class,
    })
    log.info("rules.approved", rule_id=rule_id, approved_by=body.approved_by)
    return {"approved": True, "rule": _rule_dto(record)}


@router.post("/api/rules/{rule_id}/reject")
async def reject_route(request: Request, rule_id: str, body: DecisionRequest) -> dict[str, Any]:
    """Reject a candidate -> logged, never deployed."""
    store = request.app.state.rule_store
    ledger = request.app.state.ledger
    try:
        record = store.reject(rule_id, approved_by=body.approved_by, decided_at=_iso_now())
    except RuleNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown rule {rule_id!r}"
        ) from None
    ledger.record(_iso_now(), {
        "event": "rule_rejected", "rule_id": rule_id, "approved_by": body.approved_by,
        "decided_at": record.decided_at,
    })
    log.info("rules.rejected", rule_id=rule_id, approved_by=body.approved_by)
    return {"rejected": True, "rule": _rule_dto(record)}
