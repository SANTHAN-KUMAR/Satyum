"""The rule-pack registry + runner (ADR-004 §4) — selects the domain pack by document type.

Mirrors the analyzer registry pattern: one place that knows which packs exist, so adding the
land-title or legal-contract pack later is a registration, not a rewrite. The runner picks the pack for
the claim graph's document type and returns its rule results; an unrecognised type yields no results
(the analyzer reports NOT_EVALUATED — never a guessed pass).
"""

from __future__ import annotations

from collections.abc import Callable

from app.claims import ClaimGraph
from rules import financial, land, legal
from rules.contracts import RuleResult

# domain name -> (evaluate function, the doc types it handles). Adding a domain is a registration here,
# never an orchestrator edit (Open/Closed) — the analyzer routes by the claim graph's document type.
_PACKS: dict[str, tuple[Callable[..., list[RuleResult]], frozenset[str]]] = {
    "financial": (financial.evaluate, financial.HANDLED_DOC_TYPES),
    "legal_contract": (legal.evaluate, legal.HANDLED_DOC_TYPES),
    "land_title": (land.evaluate, land.HANDLED_DOC_TYPES),
}


def domain_for_doc_type(doc_type: str | None) -> str | None:
    """The rule-pack domain that judges this document type, or ``None`` if none is registered."""
    dt = (doc_type or "").upper()
    for domain, (_, doc_types) in _PACKS.items():
        if dt in doc_types:
            return domain
    return None


def run(graph: ClaimGraph, *, min_confidence: float, tolerance: float) -> tuple[str | None, list[RuleResult]]:
    """Evaluate the applicable domain pack over ``graph``; returns ``(domain, results)``.

    ``(None, [])`` when no pack handles the document type — an honest "no rules for this kind of
    document", surfaced as NOT_EVALUATED rather than a fabricated clean pass.
    """
    domain = domain_for_doc_type(graph.doc_type)
    if domain is None:
        return None, []
    evaluate, _ = _PACKS[domain]
    return domain, evaluate(graph, min_confidence=min_confidence, tolerance=tolerance)
