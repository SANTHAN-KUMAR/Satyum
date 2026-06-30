"""Layer 3/4 — the Collective Intelligence Engine (PROPOSAL-001 §6).

The system's *learning* half, built **registry before pattern engine** (§2.3). Everything here is
**non-autonomous**: it discovers and surfaces findings as :class:`~app.contracts.AdvisorySignal`s;
a human or a human-approved deterministic rule decides. The risk-engine firewall
(``risk.engine.attach_advisory``) guarantees an advisory can only ever raise a case to REVIEW —
never clear one, never enter the deterministic score, and it fails open.

Stage 2 (this module): the privacy-preserving **shared fraud registry** — "have we *seen* this exact
document / PAN / account before?" — set-membership over salted perceptual hashes and HMAC-tokenised
entity identifiers, so no raw document or PII is ever shared.
"""
