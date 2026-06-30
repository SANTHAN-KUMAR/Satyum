"""Shared result-construction + claim-access helpers for the deterministic rule packs (ADR-004 §4).

The financial, legal, and land packs all do the same three things: read a JSON-driven rule's metadata
(name/title/severity/insufficiency message), pull a numeric value through the §5.2 trust gate (so an
untrusted/laundered figure is *missing*, never scored), and build PASS/FAIL/NOT_EVALUATED results that
localize the offending field + box. Those mechanics live here once so the packs stay focused on the
domain invariants, and every pack's policy (severity, message) stays data-driven from its rulebook.
"""

from __future__ import annotations

from decimal import Decimal

from app.claims import Claim, ClaimGraph
from ontology.loader import rule_table, severity_value
from rules.contracts import Break, RuleEvidence, RuleResult, RuleStatus


def meta(domain: str, rule_id: str) -> dict:
    """The rulebook metadata for one rule (name/title/severity refs/messages)."""
    return rule_table(domain)[rule_id]


def not_evaluated(domain: str, rule_id: str) -> RuleResult:
    m = meta(domain, rule_id)
    reason = m.get("on_insufficient", {}).get("reason", "required claims absent")
    return RuleResult(rule_id, m["name"], RuleStatus.NOT_EVALUATED, None, reason)


def passed(domain: str, rule_id: str) -> RuleResult:
    m = meta(domain, rule_id)
    return RuleResult(rule_id, m["name"], RuleStatus.PASS, None, f"{m['title']}: holds")


def failed(domain: str, rule_id: str, reason: str, evidence: tuple[RuleEvidence, ...]) -> RuleResult:
    m = meta(domain, rule_id)
    sev_ref = m.get("on_fail", {}).get("severity_ref", "hard_tamper")
    return RuleResult(rule_id, m["name"], RuleStatus.FAIL, severity_value(sev_ref), reason, sev_ref, evidence)


def scalar(graph: ClaimGraph, predicate: str, gate: float) -> tuple[Decimal | None, Claim | None]:
    """A scalar numeric claim's trusted value + the claim (for localization). ``None`` ⇒ missing/untrusted."""
    claim = graph.first(predicate)
    if claim is None:
        return None, None
    if not claim.is_trusted(gate):
        return None, claim
    return claim.as_decimal(), claim


def cell(claim: Claim | None, gate: float) -> Decimal | None:
    if claim is None or not claim.is_trusted(gate):
        return None
    return claim.as_decimal()


def trusted_text(claim: Claim | None, gate: float) -> str | None:
    """A trusted string claim's value (e.g. a name/label), or ``None`` if missing/untrusted."""
    if claim is None or not claim.is_trusted(gate):
        return None
    return (claim.value or "").strip() or None


def ev(subject: str, predicate: str, claim: Claim | None, brk: Break) -> RuleEvidence:
    return RuleEvidence(
        subject=subject,
        predicate=predicate,
        bbox=claim.provenance.bbox if claim is not None else None,
        expected=str(brk.expected) if brk.expected is not None else None,
        printed=str(brk.printed) if brk.printed is not None else None,
        index=brk.index,
        detail=brk.detail,
    )
