"""Layer 5 — Anomaly Intelligence (hybrid, soft REVIEW-only) (ADR-004 §Layer-5).

Surfaces *suspicious patterns* (not contradictions) as soft risk signals: round-number synthetic salary
credits, abrupt salary jumps, cherry-picked short statement windows, dormant-account revival. Anomaly →
REVIEW; no anomaly ≠ genuine; insufficient history → NOT_EVALUATED.

Hybrid behind one ``AnomalyDetector`` interface: a deterministic statistical backbone (always-on, fully
auditable — pure NumPy/Decimal logic, no model) plus an OPTIONAL flag-gated ML lane that is additive
only (it can raise REVIEW, never approve/reject/gate) and is excluded from the determinism guarantee.
The ML lane is a seam, not a shipped fake model: a real learned detector drops in behind the interface
(see ADR-005 for the federated path). The verdict-level guarantee that anomalies never reject lives in
the Layer-7 decision brain; this package only *finds* and reports.
"""
