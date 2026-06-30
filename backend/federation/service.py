"""Registry consult/report service — turns a verification context into registry intelligence.

Two operations (PROPOSAL-001 §6.2):

  * :func:`report_fraud` — a bank that has *confirmed* a forgery contributes its non-invertible
    fingerprint (salted pHash + HMAC entity tokens) to the shared registry. No raw document / PII.
  * :func:`consult_registry` — during a new verification, salt/tokenise this document's pHash +
    extracted entities, query the registry for set-membership, and (on a hit) emit a single
    :class:`AdvisorySignal` — a finding for a human, NEVER a verdict. The risk-engine firewall
    (``attach_advisory``) ensures it can only raise the case to REVIEW and fails open if absent.

Inputs come from artifacts the deterministic core already published into ``ctx.shared`` — the pHash
(``forensics/phash.py``) and the extracted entities (``forensics/entities.py``) — so the registry
reuses real signals rather than recomputing them.
"""

from __future__ import annotations

from typing import Any

from app.contracts import AdvisorySignal
from federation.graph import ApplicationNode, EntityGraph, RingEvidence
from federation.registry import FraudRegistry, RegistryMatch, RegistryQueryResult
from federation.tokens import entity_token, entity_tokens, salt_phash
from forensics.entities import ExtractedEntities

# Registry-match suspicion: a hit is a strong, human-worthy signal, so it reliably clears the advisory
# review threshold (a registry match should always get human eyes). Scaled by match strength for
# ranking. DEFAULT — calibrate the base on real registry-match precision (CLAUDE.md §5).
_BASE_MATCH_SUSPICION = 0.60
_MAX_MATCH_SUSPICION = 0.97


def _entity_fields(entities: ExtractedEntities | None) -> dict[str, str]:
    """Map extracted identity fields to tokeniser kinds (only those present)."""
    if entities is None:
        return {}
    fields: dict[str, str] = {}
    if entities.pan:
        fields["pan"] = entities.pan
    if entities.account_number:
        fields["account"] = entities.account_number
    if entities.ifsc:
        fields["ifsc"] = entities.ifsc
    return fields


def report_fraud(
    registry: FraudRegistry,
    *,
    phash_hex: str | None,
    entities: ExtractedEntities | None,
    threat_class: str,
    label: str,
    bank_id: str,
    timestamp: str,
    salt_hex: str,
    pepper: bytes,
) -> None:
    """Contribute a confirmed-fraud fingerprint to the shared registry (salted + tokenised)."""
    salted = salt_phash(phash_hex, salt_hex) if phash_hex else None
    tokens = entity_tokens(_entity_fields(entities), pepper)
    registry.report(
        label=label, threat_class=threat_class, bank_id=bank_id, timestamp=timestamp,
        salted_phash=salted, entity_tokens=tokens,
    )


def _describe(match: RegistryMatch) -> tuple[str, float]:
    """Build the mandatory human explanation + the advisory suspicion for a registry hit."""
    parts: list[str] = []
    if match.phash_distance is not None:
        parts.append(f"perceptual match (Hamming {match.phash_distance})")
    if match.matched_token_kinds:
        parts.append("shared " + ", ".join(match.matched_token_kinds))
    reuse = "; ".join(parts) or "entity reuse"
    explanation = (
        f"matches a document flagged at a peer bank — threat class {match.threat_class!r}: {reuse}; "
        f"seen at {match.banks_seen} bank(s). Registry finding for human review — not a verdict."
    )
    suspicion = min(_MAX_MATCH_SUSPICION, _BASE_MATCH_SUSPICION + 0.4 * match.strength)
    return explanation, suspicion


def query_registry(
    registry: FraudRegistry,
    *,
    phash_hex: str | None,
    entities: ExtractedEntities | None,
    salt_hex: str,
    pepper: bytes,
    hamming_threshold: int,
) -> RegistryQueryResult:
    """Salt/tokenise this document's pHash + entities and run the raw PSI-style membership query."""
    candidates = [salt_phash(phash_hex, salt_hex)] if phash_hex else []
    tokens = entity_tokens(_entity_fields(entities), pepper)
    if not candidates and not tokens:
        return RegistryQueryResult()  # nothing to look up
    return registry.query(
        salted_phashes=candidates, entity_tokens=tokens, hamming_threshold=hamming_threshold
    )


def consult_registry(
    registry: FraudRegistry,
    *,
    phash_hex: str | None,
    entities: ExtractedEntities | None,
    salt_hex: str,
    pepper: bytes,
    hamming_threshold: int,
) -> list[AdvisorySignal]:
    """Query the registry for this document; return advisory findings (empty if no intersection)."""
    result = query_registry(
        registry, phash_hex=phash_hex, entities=entities,
        salt_hex=salt_hex, pepper=pepper, hamming_threshold=hamming_threshold,
    )
    match = result.best
    if match is None:
        return []

    explanation, suspicion = _describe(match)
    return [AdvisorySignal(
        source="fraud_registry",
        suspicion=suspicion,
        explanation=explanation,
        confidence=min(1.0, 0.7 + 0.1 * match.banks_seen),
        measurements={
            "matched_label": match.label,
            "threat_class": match.threat_class,
            "phash_distance": match.phash_distance,
            "matched_token_kinds": list(match.matched_token_kinds),
            "banks_seen": match.banks_seen,
            "seen_count": match.seen_count,
        },
    )]


# --- ring detection (cross-bank entity graph, §6.3.2) --------------------------------------------

# Linkage identifier kinds the graph tracks (application/behavioural telemetry — the §6.1 scope
# expansion). Each is tokenised with the pepper before it touches the graph (never raw — §10).
RING_LINKAGE_KINDS = ("device", "payout_account", "employer", "pan", "account", "phone")

_RING_BASE_SUSPICION = 0.65
_RING_MAX_SUSPICION = 0.97


def add_application(
    graph: EntityGraph,
    *,
    case_id: str,
    bank_id: str,
    identifiers: dict[str, str],
    pepper: bytes,
) -> None:
    """Tokenise an application's linkage identifiers and add it to the cross-bank entity graph.

    ``identifiers`` is ``{kind: raw_value}`` for any of ``RING_LINKAGE_KINDS`` that are present; each
    is HMAC-tokenised so the graph holds only non-invertible tokens (privacy by construction).
    """
    tokens = {
        kind: entity_token(kind, value, pepper)
        for kind, value in identifiers.items()
        if kind in RING_LINKAGE_KINDS and value
    }
    graph.add(ApplicationNode(case_id=case_id, bank_id=bank_id, linkage_tokens=tokens))


def _ring_advisory(ring: RingEvidence) -> AdvisorySignal:
    suspicion = min(_RING_MAX_SUSPICION, _RING_BASE_SUSPICION + 0.3 * ring.strength)
    return AdvisorySignal(
        source="ring_evidence",
        suspicion=suspicion,
        explanation=ring.explanation,
        confidence=min(1.0, 0.6 + 0.08 * len(ring.banks)),
        measurements={
            "members": list(ring.members),
            "banks": list(ring.banks),
            "shared_identifiers": ring.shared_identifiers,
            "weight_sum": ring.weight_sum,
            "strength": ring.strength,
        },
    )


def ring_advisories_for(
    graph: EntityGraph,
    case_id: str,
    *,
    min_ring_size: int = 3,
    ring_weight_threshold: float = 1.0,
) -> list[AdvisorySignal]:
    """If ``case_id`` belongs to a detected ring, emit a ``ring_evidence`` advisory (else empty)."""
    rings = graph.rings_for(
        case_id, min_ring_size=min_ring_size, ring_weight_threshold=ring_weight_threshold
    )
    return [_ring_advisory(r) for r in rings]


def advise_from_context(
    registry: FraudRegistry,
    ctx_shared: dict[str, Any],
    *,
    salt_hex: str,
    pepper: bytes,
    hamming_threshold: int,
) -> list[AdvisorySignal]:
    """Consult the registry using artifacts the deterministic core already published into ``ctx.shared``.

    Reads the computed pHash (``forensics/phash.py``) and extracted entities (``forensics/entities.py``)
    — never recomputes them — and returns advisory findings. Fail-open: missing artifacts ⇒ no finding.
    """
    phash_hex = ctx_shared.get("phash_hex")
    entities = ctx_shared.get("entities")
    return consult_registry(
        registry,
        phash_hex=phash_hex if isinstance(phash_hex, str) else None,
        entities=entities if isinstance(entities, ExtractedEntities) else None,
        salt_hex=salt_hex,
        pepper=pepper,
        hamming_threshold=hamming_threshold,
    )
