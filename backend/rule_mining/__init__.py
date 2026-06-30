"""Stage 3 — the rule-discovery loop (PROPOSAL-001 §6.3.1).

The mechanism that keeps the federated pattern engine explainable AND central: **FL is a hypothesis
generator; humans and deterministic rules are the adjudicators.** A federated miner proposes a
*candidate rule* (a conjunction of predicates over engineered features); a fraud analyst reviews it
(evidence + measured support/confidence + back-test) and either approves it — at which point it becomes
an **ordinary auditable deterministic rule in Layer 2**, firing explainably and hash-chained like any
other signal — or rejects it (logged, not deployed).

Now a judge's "why is this suspicious?" is answered by *"it matches rule R-2026-014, discovered across
the network and approved by an analyst on <date>: new employer + high loan + night submission +
device linked to 3 prior applications"* — admissible, contestable, auditable — NOT "the model said 91%".

Honesty scope (PROPOSAL-001 §10 / CLAUDE.md §3.3): the **rule-promotion mechanism is fully real**. The
**mining** is a genuine but **single-round PoC** — a real coverage-based miner that finds predicates
which actually discriminate on the supplied labelled data (measured support/confidence, never invented
numbers). The *federated transport* (training across banks via secure aggregation without pooling raw
data) is the architectural/Stage-3 part; here the miner runs on engineered features as if already
pooled. We never fake a trained global model or claim accuracy we did not measure.
"""
