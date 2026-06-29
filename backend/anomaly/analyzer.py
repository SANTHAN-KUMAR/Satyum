"""Layer 5 analyzer: run the anomaly detectors over the claim graph and emit a soft REVIEW signal.

Composes the always-on deterministic backbone with any flag-gated ML lane (none shipped in the POC — a
real learned detector drops in behind ``AnomalyDetector``; see ADR-005). A triggered anomaly produces a
VALID signal whose suspicion is **capped at the ontology's ``review_only`` band**, so anomalies nudge
toward REVIEW but can never, on their own, reach the REJECT band — the hard "anomaly alone never
rejects" guarantee is enforced structurally in the Layer-7 decision brain. No anomaly ≠ genuine; no
assessable data ⇒ NOT_EVALUATED (never a clean pass on absent evidence).
"""

from __future__ import annotations

import logging

from anomaly.backbone import DeterministicAnomalyBackbone
from anomaly.interface import AnomalyDetector
from app.claims import ClaimGraph
from app.config import settings
from app.contracts import AnalysisContext, EvidenceRegion, LayerSignal, Mode
from ontology.loader import severity_value
from rules.financial import BANK_STATEMENT_TYPES

logger = logging.getLogger(__name__)


def _build_backbone() -> DeterministicAnomalyBackbone:
    return DeterministicAnomalyBackbone(
        min_confidence=settings.vlm_min_confidence,
        round_base=settings.anomaly_round_base,
        round_fraction_threshold=settings.anomaly_round_fraction_threshold,
        min_salary_credits=settings.anomaly_min_salary_credits,
        salary_jump_ratio=settings.anomaly_salary_jump_ratio,
        short_window_days=settings.anomaly_short_window_days,
    )


class AnomalyIntelligenceAnalyzer:
    """Hybrid anomaly layer: deterministic backbone (+ optional ML lane), REVIEW-only soft signals."""

    name = "anomaly_intelligence"
    layer = 3  # Tier-2 soft-signal band; runs after the consistency rules
    mode = Mode.FILE
    order = 50

    def __init__(self, detectors: list[AnomalyDetector] | None = None) -> None:
        if detectors is not None:
            self._detectors = detectors
        else:
            self._detectors = [_build_backbone()]
            # ML lane (ADR-004 §Layer-5): additive, REVIEW-only, off by default. Honest seam — a real
            # learned detector is appended here when configured; we ship no fabricated model.
            if settings.anomaly_ml_enabled:
                logger.warning(
                    "SATYUM_ANOMALY_ML_ENABLED is set but no ML anomaly detector is registered; "
                    "running the deterministic backbone only (no fabricated model)."
                )

    def applicable(self, ctx: AnalysisContext) -> bool:
        graph = ctx.shared.get("claim_graph")
        return isinstance(graph, ClaimGraph) and (graph.doc_type or "").upper() in BANK_STATEMENT_TYPES

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        graph = ctx.shared.get("claim_graph")
        if not isinstance(graph, ClaimGraph):
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no claim graph available for anomaly analysis"
            )

        findings = [f for d in self._detectors for f in d.detect(graph)]
        evaluated = [f for f in findings if f.evaluated]
        triggered = [f for f in evaluated if f.triggered]

        summary = [
            {
                "anomaly_id": f.anomaly_id,
                "name": f.name,
                "evaluated": f.evaluated,
                "triggered": f.triggered,
                "experimental": f.experimental,
                "reason": f.reason,
            }
            for f in findings
        ]
        measurements = {
            "findings": summary,
            "triggered_count": len(triggered),
            "evaluated_count": len(evaluated),
            "review_only": True,  # this signal can never reach the REJECT band on its own
        }

        if not evaluated:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "no anomaly check had sufficient (trusted) data to evaluate",
                **measurements,
            )

        if not triggered:
            return LayerSignal.valid(
                self.name,
                self.layer,
                self.mode,
                suspicion=0.0,
                weight=settings.weight_anomaly,
                reason=f"{len(evaluated)} anomaly check(s) ran; no suspicious pattern found",
                measurements=measurements,
            )

        # Cap at the review_only band so anomalies route to REVIEW, never to REJECT, on their own.
        suspicion = min(severity_value("review_only"), 1.0)
        regions = [
            EvidenceRegion(bbox=b, label=f"anomaly: {f.name}", source=self.name)
            for f in triggered
            for b in f.evidence_bboxes
        ]
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            suspicion=suspicion,
            weight=settings.weight_anomaly,
            reason="REVIEW-only anomalies: " + "; ".join(f.reason for f in triggered),
            evidence_regions=regions,
            measurements=measurements,
        )
