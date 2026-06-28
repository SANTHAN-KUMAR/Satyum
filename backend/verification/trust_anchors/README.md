# Trust anchors (pinned public roots only — NEVER private keys)

`PadesSignatureAnalyzer` and `C2paProvenanceAnalyzer` load every `*.pem` / `*.crt` / `*.cer` /
`*.der` file in this directory as a **pinned trust root** and require a document's signature chain
to terminate at one of them (CLAUDE.md §10, BUILD-MANIFEST). With **no** anchors present, both
analyzers fail **closed** (`ERROR`) — they never assert trust against an empty store.

In production this holds the **CCA-India PKI** root that DigiLocker-issued documents, signed bank
e-statements, and signed land RoR/EC chain to (BUILD-MANIFEST: the Adobe "Signature Not Verified"
is a *missing root*, not a missing signature — install the CCA root here and the chain verifies).

Only **public** certificates belong here. No private keys, ever (CLAUDE.md §10 — secrets are
gitignored). Tests generate their own throwaway test CA in a temp dir and point the analyzer at it
via the `anchor_dir` constructor argument, so this directory stays free of test material.
