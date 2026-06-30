"""Source-pull provider adapters (PROPOSAL-001 §4 — Stage 1).

The *source-pull-first* philosophy: the cheapest way to beat a forgery is to never accept a
forgeable file — pull the document straight from its issuer (DigiLocker / Account Aggregator) where
it arrives cryptographically signed, so integrity is answered at the root. Manual upload and live
camera are fallbacks, used only when no verifiable source exists.

Every provider implements one internal :class:`~providers.contracts.SourceProvider` interface and
returns a normalised :class:`~providers.contracts.SourceResult`; the orchestration never sees a
provider-specific shape (Dependency Inversion, mirroring the analyzer registry — CLAUDE.md §4).

Honesty guard (CLAUDE.md §3.4, PROPOSAL-001 §4.4): every adapter declares its real
``signature_status`` and, when a regulated credential is genuinely required, a precise ``gate``
label. "Simulated" must mean *real sandbox client + real signature verifier* — NEVER fabricated
data presented as live.
"""
