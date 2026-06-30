# Trust anchors (pinned public roots only — NEVER private keys)

These roots back **Layer 1 — Provenance / Source Verification**, the authoritative first tier of the
v2 waterfall ([ADR-004 §3](../../../architecture/ADR-004-v2-progressive-evidence-architecture.md)).
`PadesSignatureAnalyzer` and `C2paProvenanceAnalyzer` load every `*.pem` / `*.crt` / `*.cer` /
`*.der` file in this directory as a **pinned trust root** and require a document's signature chain
to terminate at one of them (CLAUDE.md §10, [ADR-004 §1/§7](../../../architecture/ADR-004-v2-progressive-evidence-architecture.md)).
With **no** anchors present, both analyzers fail **closed** (`ERROR`) — they never assert trust
against an empty store.

In production this holds the **CCA-India PKI** root that DigiLocker-issued documents, signed bank
e-statements, and signed land RoR/EC chain to (the Adobe "Signature Not Verified" is a *missing
root*, not a missing signature — install the CCA root here and the chain verifies). Dropping the
real CCA root in is the load-bearing carry-over gate that makes Layer 1 production-true
([ADR-004 §3 Layer 1 — HARDEN](../../../architecture/ADR-004-v2-progressive-evidence-architecture.md)).

Layer 1 stays **authoritative but not dispositive** in v2: a verified signature proves
*byte-authenticity, not claim-truthfulness*, so the document's claims still flow into deterministic
rule and corroboration checks downstream — a cryptographically genuine statement can still carry an
income that contradicts the ITR ([ADR-004 §3 Layer 1 — v2 CHANGE](../../../architecture/ADR-004-v2-progressive-evidence-architecture.md)).

Only **public** certificates belong here. No private keys, ever (CLAUDE.md §10 — secrets are
gitignored). Tests generate their own throwaway test CA in a temp dir and point the analyzer at it
via the `anchor_dir` constructor argument, so this directory stays free of test material.
