"""Layer 2 orchestrator analyzer: read the document → publish a cross-read-verified claim graph.

This is the single analyzer the orchestrator runs for VLM understanding. It renders the page, asks the
configured (possibly language-routed) extractor to transcribe it, fuses that with the OCR cross-read
into a :class:`~app.claims.ClaimGraph`, and publishes the graph on ``ctx.shared['claim_graph']`` for the
deterministic layers (4/6/7) to judge.

Like the legacy OCR bridge, it EXTRACTS — it does not score tampering — so its own signal is
``NOT_EVALUATED`` carrying the extraction provenance (model id, prompt hash, cross-read agreement rate,
the disagreeing cells). The decision is downstream and deterministic; this layer can never move a
verdict (ADR-004 §2). It fails closed throughout: no reader configured ⇒ NOT_EVALUATED (honest gate);
a render/parse fault ⇒ ERROR (pushes toward REVIEW), never a fabricated pass.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.contracts import AnalysisContext, EvidenceRegion, LayerSignal, Mode, SignalStatus
from forensics.extraction.builder import ClaimGraphBuilder
from forensics.extraction.cross_read import CrossReadEnsemble, default_ensemble
from forensics.extraction.factory import build_default_extractor
from forensics.extraction.interface import (
    PageImage,
    RawExtraction,
    VLMExtractionError,
    VLMExtractor,
    VLMUnavailable,
)
from forensics.extraction.render import render_pages

logger = logging.getLogger(__name__)


class VLMClaimGraphAnalyzer:
    """Reads an arbitrary document into a verified claim graph (ADR-004 Layer 2/3)."""

    name = "vlm_claim_graph"
    layer = 3  # runs in the Tier-2 understanding band, before the deterministic consumers
    mode = Mode.FILE  # the file/understanding path; camera (Tier 3) is a separate escalation
    order = 6  # after the legacy OCR publish (order 5), before arithmetic/forensics consumers

    def __init__(
        self,
        *,
        extractor: VLMExtractor | None = None,
        ensemble: CrossReadEnsemble | None = None,
        min_confidence: float | None = None,
        arithmetic_abs_tolerance: float | None = None,
    ) -> None:
        # All optional so the registry builds the production wiring from settings, while tests inject a
        # scripted extractor + a controlled ensemble. None ⇒ lazily resolved from config on first use.
        self._injected_extractor = extractor
        self._ensemble = ensemble
        self._min_confidence = min_confidence
        self._tol = arithmetic_abs_tolerance
        self._resolved_extractor: VLMExtractor | None = None
        self._extractor_resolved = False

    # --- lazy resolution from settings (cached) ---------------------------------------------------

    def _extractor(self) -> VLMExtractor | None:
        if self._injected_extractor is not None:
            return self._injected_extractor
        if not self._extractor_resolved:
            self._resolved_extractor = build_default_extractor(settings)
            self._extractor_resolved = True
        return self._resolved_extractor

    def _get_ensemble(self) -> CrossReadEnsemble:
        if self._ensemble is None:
            self._ensemble = default_ensemble()
        return self._ensemble

    def _min_conf(self) -> float:
        return self._min_confidence if self._min_confidence is not None else settings.vlm_min_confidence

    def _tolerance(self) -> float:
        return self._tol if self._tol is not None else settings.arithmetic_abs_tolerance

    # --- analyzer protocol ------------------------------------------------------------------------

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and ctx.file_bytes is not None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        extractor = self._extractor()
        if extractor is None or not extractor.available:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "VLM extractor not configured — set SATYUM_VLM_PROVIDER + SATYUM_VLM_API_KEY "
                "(extraction is the only probabilistic step; it never moves a verdict)",
                extractor=(extractor.name if extractor else None),
            )

        try:
            pages, source_kind = render_pages(ctx, max_pages=settings.vlm_max_pages)
        except ImportError as exc:  # missing render dep (pymupdf/PIL) → fail-closed
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"render dependency unavailable: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 — any render failure fails closed, never a pass
            return LayerSignal.error(self.name, self.layer, self.mode, f"render failed: {exc}")
        if not pages:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, source_kind)

        # Extract EVERY page. A statement's invariants (closing balance, net reconciliation) are only
        # correct over the complete transaction set, so a partial extraction would risk falsely failing a
        # genuine document — therefore any page that cannot be read fails the whole document closed
        # (NOT_EVALUATED/ERROR), never a verdict on a partial set (CLAUDE.md §4).
        extractions: list[tuple[RawExtraction, PageImage]] = []
        for page in pages:
            try:
                raw = extractor.extract(page, doc_type_hint=ctx.doc_type)
            except VLMUnavailable as exc:  # config/credential/quota gate → honest pending
                return LayerSignal.not_evaluated(self.name, self.layer, self.mode, f"VLM unavailable: {exc}")
            except VLMExtractionError as exc:  # real fault → fail-closed ERROR
                return LayerSignal.error(self.name, self.layer, self.mode, f"VLM extraction failed: {exc}")
            except Exception as exc:  # noqa: BLE001 — never let the reader crash the verdict
                return LayerSignal.error(self.name, self.layer, self.mode, f"VLM extraction error: {exc!r}")
            extractions.append((raw, page))

        raw = extractions[0][0]
        source = f"vlm:{raw.model_id}" if raw.model_id else extractor.name
        builder = ClaimGraphBuilder(self._get_ensemble(), arithmetic_abs_tolerance=self._tolerance())
        doc_id = ctx.file_name or ctx.session_id
        graph = builder.build_multi(extractions, doc_id=doc_id, source=source)

        # Publish for the deterministic layers (4 rule packs, 6 corroboration, 7 decision brain).
        ctx.shared["claim_graph"] = graph
        if graph.doc_type and graph.doc_type != "OTHER":
            ctx.doc_type = graph.doc_type

        failures = graph.cross_read_failures()
        evidence = [
            EvidenceRegion(
                bbox=c.provenance.bbox,
                label=f"cross-read disagreement on {c.subject}.{c.predicate}: "
                f"{c.provenance.cross_read_detail}",
                source=self.name,
            )
            for c in failures
            if c.provenance.bbox is not None
        ]
        agreement = graph.cross_read_agreement_rate()
        measurements = {
            "extractor": extractor.name,
            "model_id": raw.model_id,
            "prompt_hash": raw.prompt_hash,
            "doc_type": graph.doc_type,
            "primary_language": graph.primary_language,
            "source_kind": source_kind,
            "pages_extracted": len(extractions),
            "claims_total": len(graph.claims),
            "numeric_claims": len(graph.numeric_claims()),
            "cross_read_agreement_rate": agreement,
            "cross_read_failures": len(failures),
            "cross_read_readers": self._get_ensemble().reader_names,
            "trusted_claims": len(graph.trusted(self._min_conf())),
            "min_confidence_gate": self._min_conf(),
        }
        reason = (
            f"extracted {len(graph.claims)} claim(s) from a {graph.doc_type or 'document'} via "
            f"{extractor.name}; {len(graph.numeric_claims())} numeric claim(s) cross-read"
        )
        if failures:
            reason += f", {len(failures)} cell(s) failed the OCR cross-read (held pending)"

        # Extraction, not judgement: NOT_EVALUATED with full provenance. The cross-read failures are
        # surfaced as evidence + measurements for the console and the downstream sufficiency gate.
        return LayerSignal(
            name=self.name,
            layer=self.layer,
            mode=self.mode,
            status=SignalStatus.NOT_EVALUATED,
            reason=reason,
            evidence_regions=evidence,
            measurements=measurements,
            producing_mode=self.mode,
        )
