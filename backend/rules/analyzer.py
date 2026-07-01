"""Layer 4 analyzer: judge the claim graph with the deterministic domain rule pack (ADR-004 §4).

Reads the cross-read-verified claim graph published by Layer 2 (``ctx.shared['claim_graph']``), runs
the rule pack for the document's type, and emits ONE aggregate :class:`LayerSignal` — VALID with a
suspicion driven by the worst violation's calibrated severity, localizing every broken cell for the
underwriter. Unlike the legacy ``arithmetic_consistency`` analyzer (which reads the brittle
``StatementData``), this one judges the template-independent claim graph, so it runs on any layout the
VLM could read.

Fail-closed: no claim graph (VLM not run) ⇒ NOT_EVALUATED; a document type with no rule pack ⇒
NOT_EVALUATED; rules that could not gather their (trusted) inputs ⇒ excluded — only a real violation
produces suspicion, and only a real check produces a clean pass.

TODO(satyum): when Layer 7 formalizes the golden-rule guards, have the risk engine prefer THIS
claim-graph pack over the legacy ``arithmetic_consistency`` when a claim graph is present, so the two
correlated arithmetic signals are not both weighted (ADR-004 §8 step 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.claims import ClaimGraph
from app.config import settings
from app.contracts import AnalysisContext, EvidenceRegion, LayerSignal, Mode
from forensics.arithmetic import (
    ARITH_MATERIAL_DELTA_FRAC,
    SUSPICION_AGGREGATE_MATERIAL,
    SUSPICION_AGGREGATE_MINOR,
    StatementData,
)
from rules import engine, financial
from rules.contracts import RuleResult, RuleStatus

# This analyzer's clean pass is substantive content evidence (the primary in-document tamper signal on
# the claim-graph path), so APPROVED may rest on it — see config.substantive_content_signals.
SIGNAL_NAME = "financial_consistency"


@dataclass
class _TypedFinancial:
    """The claim-graph financial verdict after completeness-abstain + failure-typing (KNOWN_ISSUES #4)."""

    effective_fails: list[RuleResult]  # the fails that still score (arithmetic held pending is dropped)
    suspicion: float
    severity: str
    abstain_reason: str | None  # non-None ⇒ NOT_EVALUATED (nothing left to assert)


def _aggregate_residual(fails: list[RuleResult]) -> Decimal:
    """Largest |printed − expected| across aggregate fails' evidence — grades materiality."""
    worst = Decimal(0)
    for r in fails:
        for e in r.evidence:
            if e.expected is None or e.printed is None:
                continue
            try:
                worst = max(worst, (Decimal(e.printed) - Decimal(e.expected)).copy_abs())
            except (InvalidOperation, ValueError):
                continue
    return worst


def _type_financial_fails(
    fails: list[RuleResult], graph: ClaimGraph, ctx: AnalysisContext
) -> _TypedFinancial:
    """Mirror the OCR arithmetic path (forensics/arithmetic.py) on the claim graph.

    (1) Completeness abstain: if the OCR path flagged uncaptured monetary figures on the same page, the
        extraction is incomplete — an arithmetic imbalance may be that gap, not fraud. Hold the
        arithmetic rules pending (still score any non-arithmetic fail, e.g. date order).
    (2) Failure typing: a running-balance break (F1) is strong tamper; an aggregate-only break
        (F2/F3/F4 with the row chain intact) is graded into the REVIEW band, never an auto-REJECT.
    """
    arith_fails = [r for r in fails if r.rule_id in financial.ARITHMETIC_RULES]
    other_fails = [r for r in fails if r.rule_id not in financial.ARITHMETIC_RULES]

    stmt = ctx.shared.get("statement")
    uncaptured = stmt.unstructured_money_tokens if isinstance(stmt, StatementData) else 0
    if arith_fails and uncaptured > 0:
        if other_fails:  # the arithmetic is pending, but a non-arithmetic invariant still failed
            susp = max((r.suspicion for r in other_fails if r.suspicion is not None), default=0.0)
            return _TypedFinancial(other_fails, susp, "extraction_incomplete", None)
        return _TypedFinancial(
            [], 0.0, "extraction_incomplete",
            f"{uncaptured} monetary figure(s) on the page were not captured in the extracted ledger — "
            "extraction is incomplete, so the arithmetic imbalance cannot be attributed to tampering; "
            "left pending (REVIEW), not asserted as tampered",
        )

    chain_fails = [r for r in fails if r.rule_id in financial.BALANCE_CHAIN_RULES]
    aggregate_fails = [r for r in fails if r.rule_id in financial.AGGREGATE_RULES]
    # A chain break, any non-arithmetic fail, or no aggregate involvement -> keep the rulebook severity.
    if chain_fails or other_fails or not aggregate_fails:
        susp = max((r.suspicion for r in fails if r.suspicion is not None), default=0.0)
        severity = "running_balance_break" if chain_fails else "mixed"
        return _TypedFinancial(fails, susp, severity, None)

    # Aggregate-only: every balance chains, only a stated total/closing/net is off. Grade by materiality
    # of the largest residual against the statement's scale; both bands sit in the REVIEW range so this
    # never, on its own, auto-REJECTS a genuine statement carrying an unextracted fee (KNOWN_ISSUES #4).
    scale = financial.statement_scale(graph, settings.vlm_min_confidence)
    residual = _aggregate_residual(aggregate_fails)
    material = scale > 0 and residual >= scale * Decimal(str(ARITH_MATERIAL_DELTA_FRAC))
    susp = SUSPICION_AGGREGATE_MATERIAL if material else SUSPICION_AGGREGATE_MINOR
    return _TypedFinancial(aggregate_fails, susp, "aggregate_only", None)


class ConsistencyRulesAnalyzer:
    """Runs the Layer-4 domain rule pack over the claim graph and emits the consistency signal."""

    name = SIGNAL_NAME
    layer = 3  # Tier-2 judgment band; runs after the claim graph is published
    mode = Mode.FILE
    order = 7  # after vlm_claim_graph (order 6) publishes ctx.shared['claim_graph']

    def applicable(self, ctx: AnalysisContext) -> bool:
        return isinstance(ctx.shared.get("claim_graph"), ClaimGraph)

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        graph = ctx.shared.get("claim_graph")
        if not isinstance(graph, ClaimGraph):
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no claim graph available (VLM understanding did not run)"
            )

        domain, results = engine.run(
            graph,
            min_confidence=settings.vlm_min_confidence,
            tolerance=settings.arithmetic_abs_tolerance,
        )
        if domain is None:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                f"no rule pack for document type {graph.doc_type!r}",
                doc_type=graph.doc_type,
            )

        fails = [r for r in results if r.status == RuleStatus.FAIL]
        passes = [r for r in results if r.status == RuleStatus.PASS]
        rule_summary = [
            {"rule_id": r.rule_id, "name": r.name, "status": str(r.status), "reason": r.reason}
            for r in results
        ]
        measurements = {
            "domain": domain,
            "rules_failed": len(fails),
            "rules_passed": len(passes),
            "rules": rule_summary,
            "min_confidence_gate": settings.vlm_min_confidence,
        }

        # Nothing could be asserted (every applicable rule lacked trusted inputs) → honest pending.
        if not fails and not passes:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "no financial invariant could be evaluated on trusted claims "
                "(figures absent or not cross-read-verified)",
                **measurements,
            )

        # Completeness abstain + failure typing (KNOWN_ISSUES #4): mirror the OCR arithmetic path so the
        # claim-graph judgment ALSO distinguishes "can't verify" (REVIEW) from "fraudulent" — instead of
        # asserting tampering on every broken invariant, which false-rejected genuine statements whose
        # imbalance was really an unextracted fee/charge. Financial domain only; land/legal unchanged.
        severity = "clean" if not fails else "mixed"
        if domain == financial.DOMAIN and fails:
            typed = _type_financial_fails(fails, graph, ctx)
            if typed.abstain_reason is not None:
                measurements["severity"] = typed.severity
                return LayerSignal.not_evaluated(
                    self.name, self.layer, self.mode, typed.abstain_reason, **measurements
                )
            fails = typed.effective_fails
            suspicion = typed.suspicion
            severity = typed.severity
        else:
            suspicion = max((r.suspicion for r in fails if r.suspicion is not None), default=0.0)
        measurements["severity"] = severity

        regions = [
            EvidenceRegion(
                bbox=e.bbox,
                label=f"{r.rule_id} {e.subject}.{e.predicate}: expected {e.expected}, printed {e.printed}",
                source=self.name,
            )
            for r in fails
            for e in r.evidence
            if e.bbox is not None
        ]
        if not fails:
            reason = f"all {len(passes)} financial invariant(s) reconcile"
        elif severity == "aggregate_only":
            reason = (
                f"{len(fails)} aggregate invariant(s) off but every printed balance chains — an "
                "unextracted fee/charge or an edited stated total; routed to review, not asserted as "
                "tampering: " + "; ".join(r.reason for r in fails)
            )
        else:
            reason = f"{len(fails)} invariant(s) broken — likely edited figure(s): " + "; ".join(
                r.reason for r in fails
            )
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            suspicion=suspicion,
            weight=settings.weight_arithmetic_consistency,
            reason=reason,
            evidence_regions=regions,
            measurements=measurements,
        )
