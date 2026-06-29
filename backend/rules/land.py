"""The land/title rule pack over the claim graph (ADR-004 §4, land_title.json).

Most land-title invariants are *cross-document* by nature — the deed seller must equal the Record-of-
Rights owner (L1), property identifiers must agree across deed/RoR/EC (L3), EC encumbrances must be
disclosed in the deed (L6), and a chain of title links successive deeds (L7). Those are **bundle**
judgments and belong to Layer-6 corroboration (recorded as the land-bridge follow-on, below), not to a
single-document pack.

What is genuinely a *within-deed* invariant — and a strong one — is **L2, the registration window**
(Registration Act 1908 s.23): a sale deed must be registered within four months of its execution, and a
registration date cannot precede execution. An out-of-window or pre-execution registration is a real,
explainable title defect this pack catches deterministically.

Honest scope (per the rulebook coverage_notes): state-fragmented data (per-state stamp/guidance tables
L5, RoR-variant/ParcelId parsing, bigha/ankanam area units) stays NOT_EVALUATED until configured —
never a fabricated pass (CLAUDE.md §3.4). The cross-document rules land with the Layer-6 land bridge.
"""

from __future__ import annotations

from decimal import Decimal

from app.claims import Claim, ClaimGraph
from rules.checks import date_within
from rules.contracts import RuleResult
from rules.dates import parse_date
from rules.packbase import ev, failed, meta, not_evaluated, passed, trusted_text

DOMAIN = "land_title"

# Document types this single-document pack judges. The cross-document types (RECORD_OF_RIGHTS,
# ENCUMBRANCE_CERTIFICATE) participate only via the Layer-6 land bridge, so they are NOT routed here.
HANDLED_DOC_TYPES = frozenset({"SALE_DEED", "GIFT_DEED", "MORTGAGE_DEED"})


def _parse_date_claim(claim: Claim | None, gate: float):
    value = trusted_text(claim, gate)
    return parse_date(value) if value else None


def l2_registration_window(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """L2 — registration within the legal window after execution (RA 1908 s.23; not before execution)."""
    execution = _parse_date_claim(graph.first("execution_date"), gate)
    registration = _parse_date_claim(graph.first("registration_date"), gate)
    max_months = int(meta(DOMAIN, "L2").get("bind", {}).get("max_offset", {}).get("value", 4))
    outcome = date_within(registration, execution, max_months)
    if not outcome.evaluated:
        return not_evaluated(DOMAIN, "L2")
    if outcome.passed:
        return passed(DOMAIN, "L2")
    brk = outcome.breaks[0]
    return failed(
        DOMAIN, "L2", f"registration outside the legal window: {brk.detail}",
        (ev("RegistrationEvent", "registration_date", graph.first("registration_date"), brk),),
    )


# rule_id -> (function, applicable doc types). The within-deed rules only; cross-document L1/L3/L6/L7
# are the Layer-6 land bridge (TODO below).
_RULES: list[tuple[str, object, frozenset[str]]] = [
    ("L2", l2_registration_window, HANDLED_DOC_TYPES),
]

# TODO(satyum): Layer-6 land bridge — L1 (deed seller == RoR owner), L3 (property identifiers agree
# across deed/RoR/EC), L6 (EC encumbrances disclosed in the deed), L7 (chain of title across successive
# deeds). These are bundle-level corroboration over multiple claim graphs (like rules/corroboration.py's
# income bridge), to be wired alongside the cross-document graph. The check_kinds they need
# (fuzzy_match, consistency_across, set_subset, sequence_monotonic+chain_link) already exist.


def evaluate(graph: ClaimGraph, *, min_confidence: float, tolerance: float) -> list[RuleResult]:
    """Run every within-document land rule applicable to the deed's document type."""
    doc_type = (graph.doc_type or "").upper()
    tol = Decimal(str(tolerance))
    results: list[RuleResult] = []
    for _rule_id, fn, doc_types in _RULES:
        if doc_type not in doc_types:
            continue
        results.append(fn(graph, min_confidence, tol))  # type: ignore[operator]
    return results
