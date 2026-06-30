"""End-to-end waterfall tests: real analyzers through the orchestrator + risk engine + audit.

Also verifies the cardinal rules: an analyzer that raises becomes ERROR (never crashes the verdict,
never a silent pass), and the mode-tagging invariant holds.
"""

from __future__ import annotations

from app.contracts import AnalysisContext, LayerSignal, Mode, SignalStatus, Verdict
from app.orchestrator import run_verification
from app.registry import AnalyzerRegistry
from forensics.arithmetic import ArithmeticConsistencyAnalyzer
from risk.audit import AuditLedger
from tests.builders import genuine_statement, tampered_balance_statement

TS = "2026-06-28T12:00:00Z"


def _registry() -> AnalyzerRegistry:
    reg = AnalyzerRegistry()
    reg.register(ArithmeticConsistencyAnalyzer())
    return reg


def _file_ctx(stmt) -> AnalysisContext:
    ctx = AnalysisContext(session_id="s", intake_mode=Mode.FILE, doc_type="financial_statement")
    ctx.shared["statement"] = stmt
    return ctx


def test_genuine_document_routes_to_review_end_to_end():
    # ADR-004 §7 #2: a lone unsigned statement with clean arithmetic but no cross-source corroboration
    # and no provenance is indeterminate -> REVIEW (fail-closed), never auto-APPROVE. Approval requires
    # corroboration (bundle) or a verified source (provenance path).
    ts = run_verification(_file_ctx(genuine_statement()), _registry(), AuditLedger(), TS)
    assert ts.verdict == Verdict.REVIEW
    assert ts.evidence_pack["verdict"] == "REVIEW"


def test_tampered_document_rejects_end_to_end():
    ts = run_verification(_file_ctx(tampered_balance_statement()), _registry(), AuditLedger(), TS)
    assert ts.verdict == Verdict.REJECTED
    assert ts.evidence_pack["tamper_evidence_regions"], "rejection must surface evidence"


class _BoomAnalyzer:
    name = "boom"
    layer = 3
    mode = Mode.FILE

    def applicable(self, ctx):  # noqa: ANN001
        return True

    def analyze(self, ctx):  # noqa: ANN001
        raise RuntimeError("detector crashed")


def test_raising_analyzer_becomes_error_and_never_approves():
    reg = _registry()
    reg.register(_BoomAnalyzer())
    ts = run_verification(_file_ctx(genuine_statement()), reg, AuditLedger(), TS)
    assert any(s.status == SignalStatus.ERROR for s in ts.signals)
    assert ts.verdict != Verdict.APPROVED and ts.fail_closed


class _CameraOnlyAnalyzer:
    name = "camera_only"
    layer = 1
    mode = Mode.CAMERA

    def applicable(self, ctx):  # noqa: ANN001
        return True

    def analyze(self, ctx):  # noqa: ANN001
        return LayerSignal.valid(self.name, 1, Mode.CAMERA, 0.0, 0.1, "ran")


def test_mode_tagging_camera_analyzer_never_runs_on_file_intake():
    reg = _registry()
    reg.register(_CameraOnlyAnalyzer())
    ts = run_verification(_file_ctx(genuine_statement()), reg, AuditLedger(), TS)
    assert all(s.name != "camera_only" for s in ts.signals)


def test_audit_chain_records_the_verdict():
    led = AuditLedger()
    run_verification(_file_ctx(genuine_statement()), _registry(), led, TS)
    ok, broken = led.verify_chain()
    assert ok and broken is None
    # the audit faithfully records the actual verdict (REVIEW for a lone unsigned statement, §7 #2)
    assert led.records()[0].payload["verdict"] == "REVIEW"
