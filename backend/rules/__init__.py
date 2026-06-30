"""Layer 4 — deterministic domain rule packs over the claim graph (ADR-004 §4).

"The model reads; deterministic rules decide." This package is the *decide* half: pure-Python checks
that recompute each domain's invariants over the canonical claim graph (Layer 3) and return
PASS/FAIL/UNKNOWN/NOT_APPLICABLE/NOT_EVALUATED — fully auditable, reproducible, and free of any model.

  * ``contracts`` — the rule-result vocabulary (status, localized evidence, check outcomes).
  * ``checks``    — the finite ``check_kinds`` catalog from ``_shared.json`` as pure functions.
  * ``financial`` — the production-depth financial pack (F1–F7), rehoming ``forensics/arithmetic.py``
    onto the claim graph and adding salary/income reconciliation.
  * ``engine``    — the pack registry + runner (selects the pack by document type).
  * ``analyzer``  — the orchestrator-facing analyzer that emits the LayerSignal.

The integration with Layer 2's trust boundary is structural: a rule only ever consumes a numeric claim
that cleared the cross-read (``Claim.is_trusted``); an untrusted figure is treated as *missing*, so a
laundered/low-confidence number can never reach a verdict as fact (ADR-004 §5.2).
"""
