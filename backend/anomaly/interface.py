"""The ``AnomalyDetector`` contract + the soft finding it returns (ADR-004 §Layer-5).

One seam for both the deterministic backbone and any optional ML lane, so the analyzer composes them
identically and a bank can audit the decision *with the ML lane removed* and get the same APPROVE/REJECT
(only REVIEW routing changes). A finding is never a verdict — it is a reason-tagged REVIEW nudge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class AnomalyFinding:
    """One anomaly check's result. ``triggered`` ⇒ a REVIEW-worthy pattern; ``evaluated=False`` ⇒
    insufficient data (e.g. no history) → reported as pending, never as 'clean' and never as a reject.
    """

    anomaly_id: str
    name: str
    evaluated: bool  # could the check run at all (enough trusted data)?
    triggered: bool  # did the suspicious pattern fire?
    reason: str
    experimental: bool = False  # True for ML-lane findings (separable from the determinism guarantee)
    evidence_bboxes: tuple[BBox, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AnomalyDetector(Protocol):
    """Examines a claim graph and returns soft anomaly findings. Never returns a verdict."""

    name: str
    experimental: bool

    def detect(self, graph: Any) -> list[AnomalyFinding]: ...
