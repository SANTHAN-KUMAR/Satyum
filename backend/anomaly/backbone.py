"""The deterministic statistical anomaly backbone (always-on, fully auditable) — ADR-004 §Layer-5.

Pure Decimal/date logic over the claim graph — no model, no hidden randomness. Implements the financial
anomalies declared in ``ontology/financial.json`` (A_FIN_1..A_FIN_4): round-number synthetic salary
credits, abrupt month-over-month salary jumps, cherry-picked short statement windows, and (history-
gated) dormant-account revival. Every detector reads ONLY trusted claims (the cross-read gate, ADR-004
§5.2) and responds to input — feed it a synthetic round-number statement and the round-number detector
fires; feed it a normal one and it does not (CLAUDE.md §3.1 self-test).

Each detector returns an :class:`AnomalyFinding`; ``evaluated=False`` is the honest "not enough data"
state (e.g. dormant-revival needs multi-month history) and is reported as pending, never as clean.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from anomaly.interface import AnomalyFinding, BBox
from app.claims import Claim, ClaimGraph
from rules.dates import parse_date

# A transaction whose narration looks like a salary inflow. Whole-word matches so "sal"/"salary" hit but
# unrelated tokens do not. Calibrated against common Indian statement narrations; expandable per corpus.
_SALARY_RE = re.compile(r"\b(sal(ary)?|payroll|wages|remuneration|stipend)\b", re.IGNORECASE)


def _looks_like_salary(description: str | None) -> bool:
    return bool(description and _SALARY_RE.search(description))


class _Row:
    """A transaction row's trusted, parsed view used by the detectors."""

    __slots__ = ("credit", "description", "posted_on", "bbox")

    def __init__(
        self, credit: Decimal | None, description: str | None, posted_on: date | None, bbox: BBox | None
    ):
        self.credit = credit
        self.description = description
        self.posted_on = posted_on
        self.bbox = bbox


class DeterministicAnomalyBackbone:
    """The always-on detectors. Configured with thresholds from settings (named, calibratable)."""

    name = "anomaly_backbone"
    experimental = False

    def __init__(
        self,
        *,
        min_confidence: float,
        round_base: int,
        round_fraction_threshold: float,
        min_salary_credits: int,
        salary_jump_ratio: float,
        short_window_days: int,
    ) -> None:
        self._gate = min_confidence
        self._round_base = round_base
        self._round_fraction = round_fraction_threshold
        self._min_salary_credits = min_salary_credits
        self._jump_ratio = Decimal(str(salary_jump_ratio))
        self._short_window_days = short_window_days

    # --- claim-graph view -------------------------------------------------------------------------

    def _rows(self, graph: ClaimGraph) -> list[_Row]:
        by_seq: dict[int, dict[str, Claim]] = {}
        for c in graph.claims:
            if c.subject.startswith("transaction_") and c.index is not None:
                by_seq.setdefault(c.index, {})[c.predicate] = c
        rows: list[_Row] = []
        for seq in sorted(by_seq):
            cells = by_seq[seq]
            credit_claim = cells.get("credit")
            desc_claim = cells.get("description")
            date_claim = cells.get("posted_on")
            credit = (
                credit_claim.as_decimal()
                if credit_claim is not None and credit_claim.is_trusted(self._gate)
                else None
            )
            rows.append(
                _Row(
                    credit=credit,
                    description=desc_claim.value if desc_claim is not None else None,
                    posted_on=parse_date(date_claim.value) if date_claim is not None else None,
                    bbox=credit_claim.provenance.bbox if credit_claim is not None else None,
                )
            )
        return rows

    def _salary_rows(self, graph: ClaimGraph) -> list[_Row]:
        return [r for r in self._rows(graph) if r.credit is not None and _looks_like_salary(r.description)]

    # --- detectors --------------------------------------------------------------------------------

    def _round_number_salary(self, graph: ClaimGraph) -> AnomalyFinding:
        rows = self._salary_rows(graph)
        if len(rows) < self._min_salary_credits:
            return AnomalyFinding(
                "A_FIN_1",
                "round_number_salary_credit",
                evaluated=False,
                triggered=False,
                reason=f"fewer than {self._min_salary_credits} salary credits to assess",
            )
        base = Decimal(self._round_base)
        round_rows = [r for r in rows if r.credit is not None and r.credit % base == 0]
        fraction = len(round_rows) / len(rows)
        triggered = fraction >= self._round_fraction
        return AnomalyFinding(
            "A_FIN_1",
            "round_number_salary_credit",
            evaluated=True,
            triggered=triggered,
            reason=(
                f"{len(round_rows)}/{len(rows)} salary credits are exact multiples of {self._round_base} "
                f"({fraction:.0%}) — synthetic-looking"
                if triggered
                else f"salary credits not suspiciously round ({fraction:.0%} multiples of {self._round_base})"
            ),
            evidence_bboxes=tuple(r.bbox for r in round_rows if r.bbox is not None),
            detail={"round_fraction": round(fraction, 3), "salary_credits": len(rows)},
        )

    def _sudden_salary_jump(self, graph: ClaimGraph) -> AnomalyFinding:
        by_month: dict[tuple[int, int], Decimal] = {}
        for r in self._salary_rows(graph):
            if r.posted_on is None or r.credit is None:
                continue
            key = (r.posted_on.year, r.posted_on.month)
            by_month[key] = by_month.get(key, Decimal(0)) + r.credit
        months = sorted(by_month)
        if len(months) < 2:
            return AnomalyFinding(
                "A_FIN_2",
                "sudden_salary_jump",
                evaluated=False,
                triggered=False,
                reason="salary credits span fewer than two months",
            )
        worst_ratio = Decimal(0)
        for prev, cur in zip(months, months[1:], strict=False):
            a, b = by_month[prev], by_month[cur]
            if a > 0:
                ratio = (b / a) if b >= a else (a / b)
                worst_ratio = max(worst_ratio, ratio)
        triggered = worst_ratio > self._jump_ratio
        return AnomalyFinding(
            "A_FIN_2",
            "sudden_salary_jump",
            evaluated=True,
            triggered=triggered,
            reason=(
                f"month-over-month salary changed by up to {worst_ratio:.1f}x (> {self._jump_ratio}x)"
                if triggered
                else f"salary stable month-over-month (max {worst_ratio:.1f}x)"
            ),
            detail={"worst_ratio": float(worst_ratio), "months": len(months)},
        )

    def _short_statement_window(self, graph: ClaimGraph) -> AnomalyFinding:
        start = graph.first("period_start")
        end = graph.first("period_end")
        d0 = parse_date(start.value) if start is not None else None
        d1 = parse_date(end.value) if end is not None else None
        if d0 is None or d1 is None:
            return AnomalyFinding(
                "A_FIN_3",
                "short_statement_window",
                evaluated=False,
                triggered=False,
                reason="statement period start/end not both present",
            )
        days = (d1 - d0).days
        triggered = 0 <= days < self._short_window_days
        evidence = tuple(
            c.provenance.bbox for c in (start, end) if c is not None and c.provenance.bbox is not None
        )
        return AnomalyFinding(
            "A_FIN_3",
            "short_statement_window",
            evaluated=True,
            triggered=triggered,
            reason=(
                f"statement covers only {days} days (< {self._short_window_days}) — possibly cherry-picked"
                if triggered
                else f"statement window is {days} days"
            ),
            evidence_bboxes=evidence,
            detail={"window_days": days},
        )

    def _dormant_account_revival(self, _graph: ClaimGraph) -> AnomalyFinding:
        # Reliable detection needs multi-statement history (a long zero-activity baseline). On a single
        # statement we cannot establish dormancy, so this is honestly gated, never a guessed pass (§3.4).
        return AnomalyFinding(
            "A_FIN_4",
            "dormant_account_revival",
            evaluated=False,
            triggered=False,
            reason="needs multi-month account history (not available from a single statement)",
            detail={"needs_history": True},
        )

    def detect(self, graph: ClaimGraph) -> list[AnomalyFinding]:
        return [
            self._round_number_salary(graph),
            self._sudden_salary_jump(graph),
            self._short_statement_window(graph),
            self._dormant_account_revival(graph),
        ]
