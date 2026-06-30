"""Adversarial tests for Layer 5 — anomaly intelligence (deterministic backbone, REVIEW-only).

Proves each detector discriminates a synthetic/suspicious statement from an organic one (CLAUDE.md
§3.1/§3.2 — would FAIL against a constant), only counts trusted salary credits (the cross-read gate),
honestly gates what it cannot assess (dormant-revival needs history → NOT_EVALUATED), and that the
aggregate signal can NEVER exceed the REVIEW-only band (anomalies nudge to REVIEW, never REJECT).
"""

from __future__ import annotations

from anomaly.analyzer import AnomalyIntelligenceAnalyzer
from anomaly.backbone import DeterministicAnomalyBackbone
from anomaly.interface import AnomalyFinding
from app.claims import Claim, ClaimGraph, ClaimProvenance
from app.contracts import AnalysisContext, Mode, SignalStatus
from ontology.loader import severity_value

GATE = 0.5


def _backbone(**over) -> DeterministicAnomalyBackbone:
    params = dict(
        min_confidence=GATE,
        round_base=5000,
        round_fraction_threshold=0.60,
        min_salary_credits=3,
        salary_jump_ratio=2.0,
        short_window_days=60,
    )
    params.update(over)
    return DeterministicAnomalyBackbone(**params)


def _money(subject, predicate, value, *, index=None, agree=True, conf=0.9) -> Claim:
    return Claim(
        subject=subject,
        predicate=predicate,
        value=str(value),
        value_type="Money",
        index=index,
        cross_read_required=True,
        provenance=ClaimProvenance(
            doc_id="d", confidence=conf, source="vlm:x", cross_read_agree=agree, bbox=(1, 2, 3, 4)
        ),
    )


def _text(subject, predicate, value, *, index=None, vt="Text") -> Claim:
    return Claim(
        subject=subject,
        predicate=predicate,
        value=value,
        value_type=vt,
        index=index,
        cross_read_required=False,
        provenance=ClaimProvenance(doc_id="d", confidence=0.9, source="vlm:x", bbox=(0, 0, 1, 1)),
    )


def _stmt(credits, *, period=("01/01/2024", "31/03/2024"), desc="NEFT SALARY CREDIT"):
    """credits: list of (amount, date_str). Each becomes a credit row with `desc` narration."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    if period:
        g.add(_text("bank_statement", "period_start", period[0], vt="Date"))
        g.add(_text("bank_statement", "period_end", period[1], vt="Date"))
    for i, (amt, d) in enumerate(credits):
        g.add(_money(f"transaction_{i}", "credit", amt, index=i))
        g.add(_text(f"transaction_{i}", "description", desc, index=i))
        g.add(_text(f"transaction_{i}", "posted_on", d, index=i, vt="Date"))
    return g


def _find(findings, anomaly_id) -> AnomalyFinding:
    return next(f for f in findings if f.anomaly_id == anomaly_id)


# --- A_FIN_1 round-number salary -----------------------------------------------------------------


def test_round_number_salary_discriminates():
    rounds = _stmt([("50000", "05/01/2024"), ("50000", "05/02/2024"), ("50000", "05/03/2024")])
    organic = _stmt([("48750.50", "05/01/2024"), ("48751.50", "05/02/2024"), ("49102.75", "05/03/2024")])
    bb = _backbone()
    assert _find(bb.detect(rounds), "A_FIN_1").triggered is True
    assert _find(bb.detect(organic), "A_FIN_1").triggered is False


def test_round_number_needs_minimum_salary_credits():
    f = _find(_backbone().detect(_stmt([("50000", "05/01/2024"), ("50000", "05/02/2024")])), "A_FIN_1")
    assert f.evaluated is False and f.triggered is False  # fewer than min_salary_credits=3


def test_round_number_ignores_non_salary_credits():
    """Round non-salary credits (e.g. ATM deposits) must not be read as synthetic salary."""
    g = _stmt(
        [("50000", "05/01/2024"), ("50000", "05/02/2024"), ("50000", "05/03/2024")],
        desc="ATM CASH DEPOSIT",
    )
    assert _find(_backbone().detect(g), "A_FIN_1").evaluated is False  # no salary credits at all


def test_round_number_only_counts_trusted_credits():
    """A salary credit whose cross-read failed is not counted → drops below the minimum (the §5.2 gate)."""
    g = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    for i, agree in enumerate([True, True, False]):  # third credit untrusted
        g.add(_money(f"transaction_{i}", "credit", "50000", index=i, agree=agree))
        g.add(_text(f"transaction_{i}", "description", "SALARY", index=i))
    assert _find(_backbone().detect(g), "A_FIN_1").evaluated is False  # only 2 trusted → below min


# --- A_FIN_2 salary jump --------------------------------------------------------------------------


def test_salary_jump_discriminates():
    jump = _stmt([("30000", "05/01/2024"), ("30000", "05/02/2024"), ("90000", "05/03/2024")])
    stable = _stmt([("30000", "05/01/2024"), ("30100", "05/02/2024"), ("30050", "05/03/2024")])
    bb = _backbone()
    assert _find(bb.detect(jump), "A_FIN_2").triggered is True
    assert _find(bb.detect(stable), "A_FIN_2").triggered is False


def test_salary_jump_needs_two_months():
    one_month = _stmt([("30000", "05/01/2024"), ("30000", "06/01/2024"), ("90000", "07/01/2024")])
    assert _find(_backbone().detect(one_month), "A_FIN_2").evaluated is False


# --- A_FIN_3 short statement window ---------------------------------------------------------------


def test_short_window_discriminates():
    short = _stmt([("48000", "05/01/2024")] * 1, period=("01/01/2024", "20/01/2024"))
    long = _stmt([("48000", "05/01/2024")] * 1, period=("01/01/2024", "31/03/2024"))
    bb = _backbone()
    assert _find(bb.detect(short), "A_FIN_3").triggered is True
    assert _find(bb.detect(long), "A_FIN_3").triggered is False


def test_short_window_not_evaluated_without_period():
    assert (
        _find(_backbone().detect(_stmt([("48000", "05/01/2024")], period=None)), "A_FIN_3").evaluated is False
    )


# --- A_FIN_4 dormant revival (honest gate) --------------------------------------------------------


def test_dormant_revival_is_history_gated():
    f = _find(_backbone().detect(_stmt([("50000", "05/01/2024")])), "A_FIN_4")
    assert f.evaluated is False and f.triggered is False and f.detail.get("needs_history") is True


# --- analyzer aggregate ---------------------------------------------------------------------------


def _ctx(graph) -> AnalysisContext:
    ctx = AnalysisContext(session_id="s", intake_mode=Mode.FILE, file_bytes=b"%PDF")
    if graph is not None:
        ctx.shared["claim_graph"] = graph
    return ctx


def test_analyzer_flags_synthetic_and_clears_organic():
    az = AnomalyIntelligenceAnalyzer()
    syn = az.analyze(
        _ctx(
            _stmt(
                [("50000", "05/01/2024"), ("50000", "05/02/2024"), ("50000", "05/03/2024")],
                period=("01/01/2024", "20/01/2024"),
            )
        )
    )
    org = az.analyze(
        _ctx(
            _stmt(
                [("48750.50", "05/01/2024"), ("48751.50", "05/02/2024"), ("49102.75", "05/03/2024")],
            )
        )
    )
    assert syn.status == SignalStatus.VALID and syn.suspicion > 0
    assert org.status == SignalStatus.VALID and org.suspicion == 0.0
    assert syn.suspicion > org.suspicion  # the discriminating property
    assert syn.evidence_regions and syn.measurements["triggered_count"] >= 1


def test_anomaly_suspicion_capped_at_review_band():
    """No combination of anomalies can push suspicion past the REVIEW-only band (never a REJECT)."""
    az = AnomalyIntelligenceAnalyzer()
    # round + short + jump all at once
    sig = az.analyze(
        _ctx(
            _stmt(
                [("30000", "05/01/2024"), ("30000", "05/02/2024"), ("90000", "05/03/2024")],
                period=("01/01/2024", "20/01/2024"),
            )
        )
    )
    assert sig.suspicion == severity_value("review_only")
    assert sig.suspicion <= 0.40  # capped — anomalies route to REVIEW, never REJECT, on their own


def test_analyzer_not_evaluated_without_data():
    az = AnomalyIntelligenceAnalyzer()
    empty = ClaimGraph(doc_id="d", doc_type="BANK_STATEMENT")
    assert az.analyze(_ctx(empty)).status == SignalStatus.NOT_EVALUATED


def test_analyzer_applicable_only_for_bank_statements():
    az = AnomalyIntelligenceAnalyzer()
    assert az.applicable(_ctx(_stmt([("50000", "05/01/2024")]))) is True
    assert az.applicable(_ctx(ClaimGraph(doc_id="d", doc_type="SALARY_SLIP"))) is False


def test_detector_seam_is_injectable():
    """The hybrid seam: the analyzer composes any AnomalyDetector list (where the ML lane would plug in)."""

    class _AlwaysFires:
        name = "stub_ml"
        experimental = True

        def detect(self, graph):
            return [
                AnomalyFinding("X", "stub", evaluated=True, triggered=True, reason="fired", experimental=True)
            ]

    sig = AnomalyIntelligenceAnalyzer(detectors=[_AlwaysFires()]).analyze(_ctx(_stmt([("1", "05/01/2024")])))
    assert sig.status == SignalStatus.VALID and sig.suspicion == severity_value("review_only")
    assert sig.measurements["findings"][0]["experimental"] is True
