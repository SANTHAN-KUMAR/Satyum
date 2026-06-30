"""Consortium fraud-registry API (PROPOSAL-001 §9.3): report a confirmed fraud, or PSI-query.

These run on the BANK's node, which holds the consortium pepper/salt: identity values supplied here
are tokenised/salted locally and only the non-invertible artifacts reach the registry. Raw PAN /
account values are NEVER logged (§10) — only the opaque label, threat class, and bank id are.

  * ``POST /api/registry/report`` — contribute a confirmed-fraud fingerprint (pHash + entity tokens).
  * ``POST /api/registry/query``  — a manual set-membership query (admin / demo "is this seen?").

The automatic consult during ``/api/verify`` is the production path; these endpoints make the
network learnable in a demo across simulated bank instances.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Form, Request

from app.config import settings
from federation.service import query_registry, report_fraud
from forensics.entities import ExtractedEntities

log = structlog.get_logger(__name__)

router = APIRouter()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _entities(pan: str | None, account: str | None, ifsc: str | None) -> ExtractedEntities:
    return ExtractedEntities(pan=pan or None, account_number=account or None, ifsc=ifsc or None)


@router.post("/api/registry/report")
async def report_route(
    request: Request,
    threat_class: str = Form(...),
    label: str = Form(...),                       # opaque case ref at this bank — NOT PII
    phash_hex: str | None = Form(default=None),
    pan: str | None = Form(default=None),
    account: str | None = Form(default=None),
    ifsc: str | None = Form(default=None),
    bank_id: str | None = Form(default=None),
) -> dict[str, Any]:
    """Report a confirmed-fraud fingerprint. Values are tokenised/salted before reaching the registry."""
    registry = request.app.state.fraud_registry
    report_fraud(
        registry,
        phash_hex=phash_hex or None,
        entities=_entities(pan, account, ifsc),
        threat_class=threat_class,
        label=label,
        bank_id=bank_id or settings.federation_bank_id,
        timestamp=_iso_now(),
        salt_hex=settings.federation_consortium_salt_hex,
        pepper=settings.federation_entity_pepper.encode("utf-8"),
    )
    # Never log the raw identifiers — only opaque metadata (§10).
    log.info("registry.report", label=label, threat_class=threat_class,
             bank_id=bank_id or settings.federation_bank_id, has_phash=bool(phash_hex))
    return {"reported": True, "registry_size": registry.size(), "label": label,
            "threat_class": threat_class}


@router.post("/api/registry/query")
async def query_route(
    request: Request,
    phash_hex: str | None = Form(default=None),
    pan: str | None = Form(default=None),
    account: str | None = Form(default=None),
    ifsc: str | None = Form(default=None),
) -> dict[str, Any]:
    """PSI-style membership query. Returns ONLY the intersecting entries (never the rest)."""
    registry = request.app.state.fraud_registry
    result = query_registry(
        registry,
        phash_hex=phash_hex or None,
        entities=_entities(pan, account, ifsc),
        salt_hex=settings.federation_consortium_salt_hex,
        pepper=settings.federation_entity_pepper.encode("utf-8"),
        hamming_threshold=int(settings.phash_hamming_threshold),
    )
    return {
        "matched": result.matched,
        "matches": [
            {
                "label": m.label,
                "threat_class": m.threat_class,
                "phash_distance": m.phash_distance,
                "matched_token_kinds": list(m.matched_token_kinds),
                "banks_seen": m.banks_seen,
                "seen_count": m.seen_count,
            }
            for m in result.matches
        ],
    }
