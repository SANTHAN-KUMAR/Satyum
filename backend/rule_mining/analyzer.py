"""PromotedRuleAnalyzer — human-approved mined rules firing as auditable deterministic signals (§6.3.1).

This is what makes the federated pattern engine explainable AND central: an approved rule is an
*ordinary* deterministic Layer-2 analyzer. It reads the case's engineered features (``ctx.features``),
fires every deployed (analyst-approved) rule that matches, and emits a ``LayerSignal`` whose reason
names the rule id, the analyst who approved it, and the exact matched conditions — so it is
explainable and hash-chained like any other deterministic signal.

Because a human approved it, it is a *deterministic* signal (it enters the score), NOT an advisory —
that is precisely the §6.3.1 resolution: FL discovers, a human adjudicates, the rule decides.

Reads the live :class:`~rule_mining.store.RuleStore`, so approving a rule activates it immediately.
"""

from __future__ import annotations

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode
from rule_mining.store import RuleStore


class PromotedRuleAnalyzer:
    name = "promoted_rules"
    layer = 3  # Tier-2 forensic layer (a deterministic rule, like the other content/consistency signals)
    mode = Mode.ANY
    order = 50  # after entity extraction (order 45); rules may reference extracted/engineered features

    def __init__(self, store: RuleStore | None = None) -> None:
        self._store = store if store is not None else RuleStore()

    def applicable(self, ctx: AnalysisContext) -> bool:
        # Only meaningful when engineered features were supplied AND at least one rule is deployed.
        return bool(ctx.features) and bool(self._store.deployed_rules())

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        deployed = self._store.deployed_rules()
        if not deployed:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no analyst-approved rules deployed",
            )
        if not ctx.features:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no application features supplied for rule evaluation",
            )

        fired = [r for r in deployed if r.rule.fires(ctx.features)]
        if not fired:
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=0.0,
                weight=settings.weight_promoted_rule,
                reason="no analyst-approved rule matched this application",
                measurements={"deployed_rules": len(deployed), "fired": []},
            )

        # The strongest firing rule drives the suspicion; all firing rules are listed for the audit.
        strongest = max(fired, key=lambda r: r.rule.suspicion)
        rule = strongest.rule
        reason = (
            f"matches rule {rule.rule_id} (approved by {strongest.approved_by or 'analyst'} on "
            f"{strongest.decided_at or 'n/a'}): {rule.describe()} "
            f"[threat: {rule.threat_class}; measured confidence {rule.confidence}, support {rule.support}]"
        )
        return LayerSignal.valid(
            self.name, self.layer, self.mode,
            suspicion=rule.suspicion,
            weight=settings.weight_promoted_rule,
            reason=reason,
            measurements={
                "deployed_rules": len(deployed),
                "fired": [
                    {"rule_id": r.rule.rule_id, "predicates": r.rule.describe(),
                     "suspicion": r.rule.suspicion, "confidence": r.rule.confidence,
                     "support": r.rule.support, "approved_by": r.approved_by,
                     "decided_at": r.decided_at, "threat_class": r.rule.threat_class}
                    for r in fired
                ],
            },
        )
