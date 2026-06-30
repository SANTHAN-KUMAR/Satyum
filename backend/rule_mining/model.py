"""The rule model: predicates, candidate rules, and their lifecycle (PROPOSAL-001 §6.3.1).

A rule is a **conjunction of predicates** over a case's engineered features — pure, deterministic
logic (no black-box ML in the decision path, CLAUDE.md §4/§11). It carries the *measured* support /
confidence / lift from mining (real numbers, §3.3) and, once human-approved, fires as an auditable
deterministic signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RuleStatus(StrEnum):
    CANDIDATE = "CANDIDATE"  # mined, awaiting analyst review
    APPROVED = "APPROVED"    # analyst-approved -> deployed as a deterministic L2 rule
    REJECTED = "REJECTED"    # analyst-rejected -> logged, never deployed


_OPS = {
    "lt": lambda x, v: x < v,
    "le": lambda x, v: x <= v,
    "gt": lambda x, v: x > v,
    "ge": lambda x, v: x >= v,
    "eq": lambda x, v: x == v,
    "ne": lambda x, v: x != v,
    "in": lambda x, v: x in v,
}

_OP_SYMBOL = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥", "eq": "=", "ne": "≠", "in": "∈"}


@dataclass(frozen=True)
class Predicate:
    """One condition over a single feature. ``matches`` is False when the feature is absent (fail-safe:
    a rule cannot fire on data it does not have — better to not fire than to fire on a guess)."""

    feature: str
    op: str
    value: Any

    def matches(self, features: dict[str, Any]) -> bool:
        if self.feature not in features:
            return False
        x = features[self.feature]
        fn = _OPS.get(self.op)
        if fn is None:
            return False
        try:
            return bool(fn(x, self.value))
        except TypeError:
            return False  # incomparable types -> does not match (never raises into the verdict)

    def describe(self) -> str:
        return f"{self.feature} {_OP_SYMBOL.get(self.op, self.op)} {self.value!r}"


@dataclass(frozen=True)
class CandidateRule:
    """A mined (or hand-written) deterministic rule. Immutable; its lifecycle is tracked by the store."""

    rule_id: str
    predicates: tuple[Predicate, ...]
    threat_class: str
    suspicion: float          # suspicion it contributes when it fires (0..1)
    support: float            # fraction of fraud cases it covers (measured on mining data)
    confidence: float         # fraction of its matches that are fraud (precision on mining data)
    lift: float               # confidence / base fraud rate
    provenance: str           # how it was discovered (e.g. "federated rule mining PoC, round 1")

    def fires(self, features: dict[str, Any]) -> bool:
        """True iff EVERY predicate matches (a conjunction). Empty rule never fires (fail-safe)."""
        return bool(self.predicates) and all(p.matches(features) for p in self.predicates)

    def describe(self) -> str:
        return " ∧ ".join(p.describe() for p in self.predicates)


@dataclass
class RuleRecord:
    """A rule plus its review lifecycle (the analyst workflow, §6.3.1)."""

    rule: CandidateRule
    status: RuleStatus = RuleStatus.CANDIDATE
    approved_by: str | None = None
    decided_at: str | None = None

    @property
    def deployed(self) -> bool:
        return self.status == RuleStatus.APPROVED
