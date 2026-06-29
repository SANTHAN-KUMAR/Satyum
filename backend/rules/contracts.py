"""The rule-result vocabulary shared by every check kind and rule pack (ADR-004 §4).

A rule never returns a bare boolean: it returns a :class:`RuleResult` whose ``status`` is one of the
ontology's five states (so "I couldn't check this" is never confused with "this passed"), and — on a
FAIL — the exact field(s) and box(es) that broke, so the underwriter sees *what changed, where*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

BBox = tuple[float, float, float, float]


class RuleStatus(StrEnum):
    """The ontology status vocabulary (_shared.json::status_vocabulary)."""

    PASS = "PASS"  # invariant holds over the present (trusted) claims
    FAIL = "FAIL"  # invariant violated; localizes the offending field(s) as tamper evidence
    UNKNOWN = "UNKNOWN"  # claims present but indeterminate (ambiguous)
    NOT_APPLICABLE = "NOT_APPLICABLE"  # rule does not apply to this document type
    NOT_EVALUATED = "NOT_EVALUATED"  # required claims absent / untrusted — honest pending, never a pass


@dataclass(frozen=True)
class Break:
    """One violated point of a check — a row of a chain, or a scalar mismatch."""

    expected: Decimal | None = None
    printed: Decimal | None = None
    index: int | None = None  # row index of a localized break (e.g. the transaction whose balance broke)
    detail: str = ""

    @property
    def delta(self) -> Decimal | None:
        if self.expected is None or self.printed is None:
            return None
        return (self.printed - self.expected).copy_abs()


@dataclass(frozen=True)
class CheckOutcome:
    """The raw result of running one ``check_kind`` over resolved inputs.

    ``evaluated=False`` means the inputs were insufficient (a required value was missing/untrusted) →
    the rule becomes NOT_EVALUATED, never a fabricated pass. ``passed`` is True only when the check
    ran AND found no break.
    """

    evaluated: bool
    breaks: tuple[Break, ...] = ()
    checks_run: int = 0

    @property
    def passed(self) -> bool:
        return self.evaluated and not self.breaks

    @classmethod
    def insufficient(cls) -> CheckOutcome:
        return cls(evaluated=False)


@dataclass(frozen=True)
class RuleEvidence:
    """A localized FAIL pointer for the evidence console — field + box + the expected vs printed value."""

    subject: str
    predicate: str
    bbox: BBox | None
    expected: str | None
    printed: str | None
    index: int | None
    detail: str


@dataclass(frozen=True)
class RuleResult:
    """One evaluated rule's outcome (wrapped into a LayerSignal by the analyzer)."""

    rule_id: str
    name: str
    status: RuleStatus
    suspicion: float | None  # from severity_bands on FAIL, else None
    reason: str
    severity_ref: str = ""
    evidence: tuple[RuleEvidence, ...] = field(default_factory=tuple)
