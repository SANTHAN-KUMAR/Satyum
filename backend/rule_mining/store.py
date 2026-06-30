"""The rule store + analyst approval lifecycle (PROPOSAL-001 §6.3.1).

Holds every candidate/approved/rejected rule. Approval is the human gate that turns an FL-discovered
candidate into a deployed deterministic rule the :class:`~rule_mining.analyzer.PromotedRuleAnalyzer` fires.
The store is the single source of truth shared between the approval API and the analyzer, so approving
a rule activates it live (no re-registration).
"""

from __future__ import annotations

from rule_mining.model import CandidateRule, RuleRecord, RuleStatus


class RuleNotFoundError(LookupError):
    """Raised when a rule id is unknown (the route maps this to HTTP 404)."""


class RuleStore:
    def __init__(self) -> None:
        self._records: dict[str, RuleRecord] = {}

    def add_candidate(self, rule: CandidateRule) -> RuleRecord:
        record = RuleRecord(rule=rule, status=RuleStatus.CANDIDATE)
        self._records[rule.rule_id] = record
        return record

    def add_candidates(self, rules: list[CandidateRule]) -> list[RuleRecord]:
        return [self.add_candidate(r) for r in rules]

    def get(self, rule_id: str) -> RuleRecord | None:
        return self._records.get(rule_id)

    def approve(self, rule_id: str, *, approved_by: str, decided_at: str) -> RuleRecord:
        record = self._require(rule_id)
        record.status = RuleStatus.APPROVED
        record.approved_by = approved_by
        record.decided_at = decided_at
        return record

    def reject(self, rule_id: str, *, approved_by: str, decided_at: str) -> RuleRecord:
        record = self._require(rule_id)
        record.status = RuleStatus.REJECTED
        record.approved_by = approved_by
        record.decided_at = decided_at
        return record

    def deployed_rules(self) -> list[RuleRecord]:
        """The APPROVED rules — what the analyzer fires (with their approval metadata for the audit)."""
        return [r for r in self._records.values() if r.deployed]

    def all(self) -> list[RuleRecord]:
        return list(self._records.values())

    def _require(self, rule_id: str) -> RuleRecord:
        record = self._records.get(rule_id)
        if record is None:
            raise RuleNotFoundError(rule_id)
        return record
