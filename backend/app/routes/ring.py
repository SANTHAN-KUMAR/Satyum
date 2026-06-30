"""Cross-bank ring-detection API (PROPOSAL-001 §6.1 / §6.3.2).

Submit an application's linkage telemetry (tokenised server-side under the consortium pepper), then
detect rings across the pooled graph, or fetch the ring evidence for one case. Raw identifiers
(device, payout account, employer) are NEVER logged or stored — only their HMAC tokens (§10).

This surface is the §6.1 *scope expansion* named honestly: application/behavioural telemetry, a new
(consented, tokenised) data surface beyond document content. Ring detection here is deterministic
graph analytics; the FL "resembles-a-ring" score is the Stage-3 layer.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Form, Request

from app.config import settings
from federation.service import RING_LINKAGE_KINDS, add_application, ring_advisories_for

log = structlog.get_logger(__name__)

router = APIRouter()


def _collect_identifiers(
    device: str | None, payout_account: str | None, employer: str | None,
    pan: str | None, account: str | None, phone: str | None,
) -> dict[str, str]:
    raw = {"device": device, "payout_account": payout_account, "employer": employer,
           "pan": pan, "account": account, "phone": phone}
    return {k: v for k, v in raw.items() if k in RING_LINKAGE_KINDS and v}


@router.post("/api/ring/application")
async def submit_application(
    request: Request,
    case_id: str = Form(...),
    bank_id: str | None = Form(default=None),
    device: str | None = Form(default=None),
    payout_account: str | None = Form(default=None),
    employer: str | None = Form(default=None),
    pan: str | None = Form(default=None),
    account: str | None = Form(default=None),
    phone: str | None = Form(default=None),
) -> dict[str, Any]:
    """Add an application's tokenised linkage features to the cross-bank entity graph."""
    graph = request.app.state.entity_graph
    identifiers = _collect_identifiers(device, payout_account, employer, pan, account, phone)
    add_application(
        graph, case_id=case_id, bank_id=bank_id or settings.federation_bank_id,
        identifiers=identifiers, pepper=settings.federation_entity_pepper.encode("utf-8"),
    )
    # Log only the case id, bank, and WHICH kinds were provided — never the raw values (§10).
    log.info("ring.application.added", case_id=case_id,
             bank_id=bank_id or settings.federation_bank_id, kinds=sorted(identifiers))
    return {"added": True, "case_id": case_id, "graph_size": graph.size()}


@router.post("/api/ring/detect")
async def detect_rings(
    request: Request,
    min_ring_size: int = Form(default=3),
    ring_weight_threshold: float = Form(default=1.0),
) -> dict[str, Any]:
    """Detect rings across the pooled graph. Returns ring evidence by identifier KIND (no raw PII)."""
    graph = request.app.state.entity_graph
    rings = graph.detect_rings(min_ring_size=min_ring_size, ring_weight_threshold=ring_weight_threshold)
    return {
        "ring_count": len(rings),
        "rings": [
            {
                "members": list(r.members),
                "banks": list(r.banks),
                "shared_identifiers": r.shared_identifiers,
                "weight_sum": r.weight_sum,
                "strength": r.strength,
                "explanation": r.explanation,
            }
            for r in rings
        ],
    }


@router.get("/api/ring/case/{case_id}")
async def ring_for_case(request: Request, case_id: str) -> dict[str, Any]:
    """Ring evidence (as advisory findings) for a single case — for the underwriter console panel."""
    graph = request.app.state.entity_graph
    advisories = ring_advisories_for(graph, case_id)
    return {
        "case_id": case_id,
        "in_ring": bool(advisories),
        "findings": [
            {"source": a.source, "suspicion": a.suspicion, "confidence": a.confidence,
             "explanation": a.explanation, "measurements": a.measurements,
             "note": "finding — not a verdict"}
            for a in advisories
        ],
    }
