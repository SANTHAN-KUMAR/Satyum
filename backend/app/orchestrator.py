"""The verification waterfall (ADR-002): run mode-valid analyzers, aggregate, audit — fail-closed.

The orchestrator is the only component that composes analyzers; analyzers never call each other.
It guarantees the cardinal banking rule (CLAUDE.md §4): an analyzer that raises an *unexpected*
exception becomes an ``ERROR`` signal (never crashes the verdict, never a silent pass), and the
risk engine degrades the verdict accordingly.
"""

from __future__ import annotations

from app.contracts import AnalysisContext, LayerSignal, Mode, TrustScore
from app.registry import AnalyzerRegistry
from risk.audit import AuditLedger
from risk.engine import aggregate
from risk.evidence import build_evidence_pack


def collect_signals(ctx: AnalysisContext, registry: AnalyzerRegistry) -> list[LayerSignal]:
    """Run every mode-valid, applicable analyzer over ``ctx`` and return the raw signals.

    This is the analyzer-composition half of :func:`run_verification`, split out so the bundle path can
    gather each document's signals, compute the bundle-level corroboration (which needs ALL documents'
    claim graphs), and only THEN aggregate each document *with* that corroboration injected (ADR-004 §6
    — a corroborated bundle can reach APPROVE, which a per-document-first aggregation cannot give). It
    upholds the cardinal rule (§4): an analyzer that raises becomes ERROR, never crashes the waterfall.
    """
    signals: list[LayerSignal] = []
    for analyzer in registry.for_mode(ctx.intake_mode):
        try:
            if not analyzer.applicable(ctx):
                continue
            signal = analyzer.analyze(ctx)
        except Exception as exc:  # noqa: BLE001 — deliberate fail-closed boundary
            # An analyzer must not be able to crash the verdict or wave a forgery through.
            signal = LayerSignal.error(
                analyzer.name, analyzer.layer, analyzer.mode, f"unhandled exception: {exc!r}"
            )

        # Defence-in-depth on the mode-tagging invariant: a file-forensic signal can never be
        # emitted as having been produced on a camera frame.
        if ctx.intake_mode == Mode.CAMERA and signal.producing_mode == Mode.FILE:
            signal = LayerSignal.error(
                analyzer.name, analyzer.layer, analyzer.mode,
                "mode-tagging violation: FILE signal on CAMERA intake (suppressed)",
            )

        signals.append(signal)
    return signals


def run_verification(
    ctx: AnalysisContext,
    registry: AnalyzerRegistry,
    ledger: AuditLedger,
    timestamp_iso: str,
) -> TrustScore:
    signals = collect_signals(ctx, registry)

    trust = aggregate(
        ctx.session_id, ctx.intake_mode, signals,
        doc_type=ctx.doc_type, source_was_pullable=ctx.source_was_pullable,
    )
    trust.evidence_pack = build_evidence_pack(trust)
    audit_trust(ledger, timestamp_iso, trust)
    return trust


def audit_trust(ledger: AuditLedger, timestamp_iso: str, trust: TrustScore) -> None:
    """Append a single document's verdict to the tamper-evident ledger (decision metadata + signal
    digests only — never document content or imagery, CLAUDE.md §10). Shared by the single-document
    and bundle paths so every document is recorded with an identical, reconstructable schema."""
    ledger.record(
        timestamp_iso,
        {
            "session_id": trust.session_id,
            "intake_mode": trust.intake_mode.value,
            "verdict": trust.verdict.value,
            "trust_score": trust.trust_score,
            "tier_reached": trust.tier_reached,
            "fail_closed": trust.fail_closed,
            "signals": [
                {"name": s.name, "status": s.status.value,
                 "suspicion": s.suspicion, "weight": s.weight}
                for s in trust.signals
            ],
        },
    )
