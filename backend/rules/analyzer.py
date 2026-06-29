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

from app.claims import ClaimGraph
from app.config import settings
from app.contracts import AnalysisContext, EvidenceRegion, LayerSignal, Mode
from rules import engine
from rules.contracts import RuleStatus

# This analyzer's clean pass is substantive content evidence (the primary in-document tamper signal on
# the claim-graph path), so APPROVED may rest on it — see config.substantive_content_signals.
SIGNAL_NAME = "financial_consistency"


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
        suspicion = max((r.suspicion for r in fails if r.suspicion is not None), default=0.0)
        reason = (
            f"all {len(passes)} financial invariant(s) reconcile"
            if not fails
            else f"{len(fails)} invariant(s) broken — likely edited figure(s): "
            + "; ".join(r.reason for r in fails)
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
