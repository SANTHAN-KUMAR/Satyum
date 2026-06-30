"""The legal-contract rule pack (G1–G6) over the claim graph (ADR-004 §4, legal_contract.json).

Deterministic *structural* axioms over loan / sale / lease agreements — the checks a forger's edit or a
spliced/incomplete draft tends to break, judged on the template-independent claim graph (so it runs on
any layout the VLM read):

  * **G1 words = figures** — the consideration (and each monetary term) written in words must equal the
    figure. The classic deterministic tamper tell: an edited figure rarely re-renders its words form.
  * **G2 term arithmetic** — effective date + term = end date.
  * **G3 party-name consistency** — each party's name agrees across the sections it appears in
    (recital / body / signature / schedule); a spliced document drifts.
  * **G4 schedule references resolve** — every referenced schedule/annexure actually exists.
  * **G5 page completeness** — printed page numbers form a complete, gap-free run.
  * **G6 execution completeness** — the required signatures, two witnesses, and an execution date.

Every rule reads only **trusted** claims (the §5.2 cross-read/confidence gate, via ``packbase``); a
missing or untrusted input yields NOT_EVALUATED, never a fabricated pass. Honest bound (per the
rulebook): semantic clause-conflict detection is out of scope for a deterministic pack and routes to
human review — this pack catches edits and structural incompleteness, not a fully self-consistent forgery.
"""

from __future__ import annotations

from decimal import Decimal

from app.claims import Claim, ClaimGraph
from rules.checks import date_offset_equals, equation, references_resolve, sequence_complete
from rules.contracts import Break, RuleEvidence, RuleResult
from rules.dates import parse_date
from rules.numwords import words_to_decimal
from rules.packbase import cell, ev, failed, meta, not_evaluated, passed, scalar, trusted_text
from rules.textmatch import all_names_agree

DOMAIN = "legal_contract"

HANDLED_DOC_TYPES = frozenset(
    {"LOAN_AGREEMENT", "SALE_AGREEMENT", "LEASE_AGREEMENT", "GUARANTEE_DEED", "GENERIC_CONTRACT"}
)
_TERM_RULES = frozenset({"LOAN_AGREEMENT", "LEASE_AGREEMENT"})  # G2 applies to fixed-term agreements
_PARTY_RULES = frozenset({"LOAN_AGREEMENT", "SALE_AGREEMENT", "LEASE_AGREEMENT", "GUARANTEE_DEED"})
_EXEC_RULES = _PARTY_RULES


def _de(rule_id: str) -> RuleResult:
    return not_evaluated(DOMAIN, rule_id)


def _pass(rule_id: str) -> RuleResult:
    return passed(DOMAIN, rule_id)


def _fail(rule_id: str, reason: str, evidence: tuple[RuleEvidence, ...] = ()) -> RuleResult:
    return failed(DOMAIN, rule_id, reason, evidence)


def _group_by_prefix(graph: ClaimGraph, prefix: str) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = {}
    for c in graph.claims:
        if c.subject.startswith(prefix):
            groups.setdefault(c.subject, []).append(c)
    return groups


def _multi_text(graph: ClaimGraph, predicate: str, gate: float) -> list[str]:
    """All trusted string values for a repeated predicate, in document order (index-sorted)."""
    return [v for c in graph.by_predicate(predicate) if (v := trusted_text(c, gate)) is not None]


# --- the rules ------------------------------------------------------------------------------------


def _words_vs_figure(words: str | None, figure: Decimal | None, tol: Decimal) -> bool | None:
    """True/False if comparable (words parse + figure present), else None (insufficient)."""
    if words is None or figure is None:
        return None
    parsed = words_to_decimal(words)
    if parsed is None:
        return None
    return equation([(1, parsed)], figure, tol).passed


def g1_amount_words_equals_figures(graph: ClaimGraph, gate: float, tol: Decimal) -> RuleResult:
    """G1 — the consideration (and each monetary term) in words equals its figure."""
    checked = 0
    evidence: list[RuleEvidence] = []
    parts: list[str] = []

    # Agreement-level consideration.
    figure, fig_claim = scalar(graph, "consideration", gate)
    words = trusted_text(graph.first("consideration_in_words"), gate)
    outcome = _words_vs_figure(words, figure, tol)
    if outcome is not None:
        checked += 1
        if outcome is False:
            evidence.append(ev("Agreement", "consideration", fig_claim,
                               _scalar_break(words, figure)))
            parsed_dec = words_to_decimal(words or "")
            parts.append(f"consideration words '{words}' ({parsed_dec}) != figure {figure}")

    # Per monetary term (also_applies_per): amount_in_words vs amount.
    for subject, claims in sorted(_group_by_prefix(graph, "monetary_term_").items()):
        by_pred = {c.predicate: c for c in claims}
        amt = cell(by_pred.get("amount"), gate)
        amt_words = trusted_text(by_pred.get("amount_in_words"), gate)
        outcome = _words_vs_figure(amt_words, amt, tol)
        if outcome is not None:
            checked += 1
            if outcome is False:
                evidence.append(ev(subject, "amount", by_pred.get("amount"),
                                   _scalar_break(amt_words, amt)))
                parts.append(f"{subject} words '{amt_words}' != figure {amt}")

    if checked == 0:
        return _de("G1")
    if evidence:
        return _fail("G1", "; ".join(parts), tuple(evidence))
    return _pass("G1")


def _scalar_break(words: str | None, figure: Decimal | None):
    parsed = words_to_decimal(words) if words else None
    return Break(expected=parsed, printed=figure)


def g2_term_arithmetic(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """G2 — effective date + term (months) == end date, within the rulebook's day tolerance."""
    start = parse_date_claim(graph.first("effective_date"), gate)
    end = parse_date_claim(graph.first("end_date"), gate)
    term_months, _ = scalar(graph, "term", gate)
    tol_days = int(meta(DOMAIN, "G2").get("bind", {}).get("tolerance_days", 1))
    months = int(term_months) if term_months is not None else None
    outcome = date_offset_equals(start, months, end, tol_days)
    if not outcome.evaluated:
        return _de("G2")
    if outcome.passed:
        return _pass("G2")
    brk = outcome.breaks[0]
    return _fail("G2", f"term arithmetic fails: {brk.detail}",
                 (ev("Agreement", "end_date", graph.first("end_date"), brk),))


def g3_party_name_consistency(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """G3 — each party's name agrees across the sections it appears in."""
    evaluated = False
    for subject, claims in sorted(_group_by_prefix(graph, "party_").items()):
        names = [v for c in claims if c.predicate == "name" and (v := trusted_text(c, gate)) is not None]
        if len(names) < 2:
            continue
        evaluated = True
        ok, pair = all_names_agree(names)
        if not ok and pair is not None:
            brk = Break(detail=f"{subject} name differs across sections: {pair[0]!r} vs {pair[1]!r}")
            return _fail("G3", f"party name differs across sections: {pair[0]!r} vs {pair[1]!r}",
                         (ev(subject, "name", claims[0], brk),))
    return _pass("G3") if evaluated else _de("G3")


def g4_schedule_references_resolve(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """G4 — every referenced schedule/annexure resolves to an existing schedule label."""
    refs = _multi_text(graph, "refers_to", gate)
    labels = _multi_text(graph, "label", gate)
    outcome = references_resolve(refs, labels)
    if not outcome.evaluated:
        return _de("G4")
    if outcome.passed:
        return _pass("G4")
    brk = outcome.breaks[0]
    return _fail("G4", f"unresolved schedule reference(s): {brk.detail}",
                 (ev("Clause", "refers_to", None, brk),))


def g5_page_completeness(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """G5 — the printed page numbers form a complete run 1..N (N = declared page count)."""
    numbers: list[int] = []
    for c in graph.by_predicate("printed_page_number"):
        v = cell(c, gate)
        if v is not None:
            numbers.append(int(v))
    count, count_claim = scalar(graph, "printed_page_count", gate)
    expected = int(count) if count is not None else None
    outcome = sequence_complete(numbers, 1, expected)
    if not outcome.evaluated:
        return _de("G5")
    if outcome.passed:
        return _pass("G5")
    brk = outcome.breaks[0]
    return _fail("G5", f"page sequence incomplete: {brk.detail}",
                 (ev("Agreement", "printed_page_count", count_claim, brk),))


def g6_execution_completeness(graph: ClaimGraph, gate: float, _tol: Decimal) -> RuleResult:
    """G6 — signatures (≥ one per party), ≥2 witnesses, and an execution date are present."""
    signatures = _multi_text(graph, "signature", gate)
    witnesses = _multi_text(graph, "witness", gate)
    exec_date = parse_date_claim(graph.first("execution_date"), gate)
    party_count = sum(
        1 for subj, claims in _group_by_prefix(graph, "party_").items()
        if any(c.predicate == "name" and trusted_text(c, gate) for c in claims)
    )
    # NOT_EVALUATED only when there is no execution block at all to assess.
    if not signatures and not witnesses and exec_date is None:
        return _de("G6")

    required_sigs = max(1, party_count)
    failures: list[str] = []
    if len(signatures) < required_sigs:
        failures.append(f"{len(signatures)} signature(s), need >= {required_sigs} (one per party)")
    if len(witnesses) < 2:
        failures.append(f"{len(witnesses)} witness(es), need >= 2")
    if exec_date is None:
        failures.append("execution is undated")
    if failures:
        brk = Break(detail="; ".join(failures))
        return _fail("G6", f"execution incomplete: {'; '.join(failures)}",
                     (ev("ExecutionBlock", "signatures", None, brk),))
    return _pass("G6")


def parse_date_claim(claim: Claim | None, gate: float):
    """Parse a trusted Date claim's value to a ``date``, or ``None`` (missing/untrusted/unparseable)."""
    value = trusted_text(claim, gate)
    return parse_date(value) if value else None


# rule_id -> (function, applicable doc types)
_RULES: list[tuple[str, object, frozenset[str]]] = [
    ("G1", g1_amount_words_equals_figures, HANDLED_DOC_TYPES),
    ("G2", g2_term_arithmetic, _TERM_RULES),
    ("G3", g3_party_name_consistency, _PARTY_RULES),
    ("G4", g4_schedule_references_resolve, HANDLED_DOC_TYPES),
    ("G5", g5_page_completeness, HANDLED_DOC_TYPES),
    ("G6", g6_execution_completeness, _EXEC_RULES),
]


def evaluate(graph: ClaimGraph, *, min_confidence: float, tolerance: float) -> list[RuleResult]:
    """Run every rule applicable to the agreement's document type."""
    doc_type = (graph.doc_type or "").upper()
    tol = Decimal(str(tolerance))
    results: list[RuleResult] = []
    for _rule_id, fn, doc_types in _RULES:
        if doc_type not in doc_types:
            continue
        results.append(fn(graph, min_confidence, tol))  # type: ignore[operator]
    return results
