"""Layer 0 — Intake + Evidence Sufficiency (ADR-004 §Layer-0, lightweight).

Before any expensive verification, classify *what* the document is and decide *what confidence is even
achievable*: a single unsigned PDF, a case-context bundle, or a corroborated set. This makes "I only
got one PDF" an explicit, honest state that the decision brain (Layer 7) can refuse to auto-approve,
rather than a silent assumption.

Deterministic by design: the doc-type classifier here is a header/keyword matcher over the PDF text
layer (NOT the VLM — that is Layer 2), so the system knows what it is holding and how strong a verdict
is possible even with no model and no API key.
"""
