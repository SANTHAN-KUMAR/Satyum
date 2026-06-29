# ADR-002 — Provenance-First Verification Waterfall

> **Still in force.** Built on by [ADR-004](ADR-004-v2-progressive-evidence-architecture.md) (the v2 architecture of record). Mode-tagging / provenance-first / fail-closed carry into v2 unchanged.

> **Status:** Accepted · 2026-06-27 · **evolves [ADR-001](ADR-001-dual-mode-and-signal-validity.md)**
> **Grounded by:** [RESEARCH-001 — Industry Landscape](RESEARCH-001-industry-landscape.md) (cited web research)
> **Scope:** Satyum — Canara Bank SuRaksha 2.0, Theme 1 (document anomaly detection for underwriting)

This ADR sharpens ADR-001 with what real institutions actually do. The goal is a **robust, resilient system that catches the fraud Canara faces during underwriting** — not a CV demo. Where this disagrees with ADR-001, this wins.

---

## Context (from RESEARCH-001)

Across financial statements, identity documents, and land/title records, the institutional first-line control is **verification against an authoritative source** (open-banking / Account Aggregator pull, government-signed chips, land registries), **not** pixel analysis of an uploaded image. Three corrections follow:

1. **Forensics is a permanent, load-bearing fallback, not a legacy path** — source connectivity has real coverage gaps (banks not on AA, thin-file/self-employed, foreign/long-tail docs, scanned paper deeds).
2. **Pixel forensics (ELA/PRNU/copy-move) is genuinely distrusted** (ELA ≈ chance per Hany Farid; ML detectors collapse on AI forgeries — TruFor AUC 0.96→0.751), **but structure/metadata + arithmetic forensics is trusted and recommended.** Do not conflate them.
3. **Camera capture is under injection attack** (synthetic streams fed past the camera; iProov: injection +783% in 2024; Arup deepfake-call loss US$25M). ISO 30107-3 liveness certification *excludes* injection. "Turn on the webcam" is not an assurance upgrade by itself.

---

## Decisions

### D1 — The verification waterfall (provenance-first). *[user-confirmed: "verify against the source of truth first"]*
The orchestrator runs three tiers in order and **fails closed** (degrades toward REVIEW/REJECT on failure or uncertainty):

- **Tier 1 — Source-of-truth verification (first-line control).** Verify the document against its issuing source / cryptographic signature *before* trusting any uploaded bytes. A passing check answers integrity at the root (a tampered upload cannot survive it); a failing check fails closed. CV forensics then render `NOT_EVALUATED("source-verified")` — not needed.
- **Tier 2 — Trusted forensic fallback (only when no verifiable source exists).** The industry-*trusted* techniques: PDF metadata/structure anomaly, template fingerprinting, **OCR + cross-field/arithmetic consistency (primary in-document tamper signal)**, font/layout anomaly, spatial copy-move, pHash resubmission. Operates on the document page whether born-digital, scanned, or a rectified camera crop.
- **Tier 3 — Live capture (in-person escalation).** WebRTC camera for wet-ink / contested / in-person documents: rectify + quality gate, the active 3D challenge, anti-spoof votes, and an injection-integrity check (D5).

### D2 — Build honesty: REAL signature verification, not simulated connectors. *[corrected by the no-mock audit — see [BUILD-MANIFEST](BUILD-MANIFEST.md)]*
The no-mock audit caught a genuine cop-out: the earlier "simulated AA / DigiLocker / registry connectors" were partly inability dressed as honesty. The integrity guarantee comes from each document's **cryptographic signature**, which we verify **offline, with no partner**.
- **Built for real (no partner):** PAdES/eIDAS signature verification (pyHanko) on signed PDFs — including **DigiLocker-issued documents, bank e-statements, and signed state land RoR/EC**, all chaining to the public **CCA-India PKI** root shipped in-repo (the Adobe "signature not verified" is only a missing root, not a missing signature); C2PA validation (**trust-list pinned**); PDF metadata/structure forensics; OCR + arithmetic-consistency engine; font/layout; copy-move; pHash; rectify + quality gate; active 3D challenge; anti-spoof votes; risk engine + Evidence Pack. **16 components are fully real.**
- **Gated, but with a REAL substitute (label the gate precisely; never present fabricated data as live):**
  - *Account Aggregator production live-pull* needs RBI/SEBI-regulated FIU onboarding — so build against a **real self-serve sandbox (Setu/Finvu)** and verify the **real FIP-signed JSON**. Only live data *freshness* is genuinely gated.
  - *NFC ePassport read is impossible in a browser* (WebNFC is NDEF-only, no ISO-7816 APDU) — the real path is a **native app** (jMRTD / NFCPassportReader + public CSCA masterlist), never a browser "pass."
  - *Injection / virtual-camera check has no real in-browser sensor attestation* — keep it **low-weight and documented-bypassable** (the real version needs native Play Integrity / DeviceCheck); it must never produce an unearned PASS.
- **Zero fabricated data presented as live.** A simulation is acceptable *only* where no real substitute exists, and must be labeled with its precise gate (regulatory credential / browser-medium limit) per [CLAUDE.md §3.4](../CLAUDE.md). Every real detector ships with the adversarial **must-fail CI fixtures** named in the BUILD-MANIFEST (e.g. a self-signed-cert PDF and an appended-bytes PDF must both FAIL signature verification).

### D3 — "Source-pull-possible but PDF-only submitted" is a red-flag signal.
If a verifiable source existed for a document (e.g. the bank is AA-enabled) but the applicant submitted only an uploaded PDF, that avoidance is itself suspicious and raises risk — mirroring how lenders treat the absence of a sourceable record.

### D4 — Tier-2 forensics uses trusted techniques only; distrusted pixel CV is excluded.
Metadata/structure/template/arithmetic are the backbone. **ELA, PRNU, steganalysis, and heavy ML pixel-tamper detection are excluded or `NOT_EVALUATED`** — near-chance, and they give false confidence against the GenAI-generated forgeries now emerging. (This also retires the file-mode ELA/stego that ADR-001 had moved to file mode — they stay out, on merit.)

### D5 — Camera mode scoped to in-person + injection-aware. *[user-confirmed]*
The active 3D challenge defends **presentation** attacks (photo-of-screen, replay shown to a camera). It does **not** stop **injection** attacks. Therefore: position camera mode for genuine in-person/branch/wet-ink capture, add a **virtual-camera / sensor-integrity check**, and state the limitation honestly in the Evidence Pack. Never present camera mode as a remote high-assurance upgrade.

### D6 — Provenance is a strong signal, not absolute proof.
Design for strip attacks, opt-in absence-of-signal, the C2PA "first-mile" gap (a device signed a file ≠ it captured the real scene; cf. the Sept 2025 Nikon Z6 III exploit), and NFC passive-authentication not detecting cloned chips. Never render "signed = authentic" as dispositive on its own; fuse with the other tiers.

### D7 — Evidence Pack reports the verification tier reached.
The Underwriter Evidence Pack (ADR-001 D7) additionally surfaces **which tier produced the verdict** (source-verified / forensic-fallback / in-person-capture), per-signal status + producing mode, the red-flag (D3) if any, and a recommended action with reasons.

---

## Consequences
- **Positive:** matches how real banks verify (defensible to bank judges); attacks fraud at the root rather than chasing pixels; resilient where source-pull is unavailable; honest about simulated rails and about what the camera can/can't stop; retires the weakest, GenAI-fragile detectors.
- **Costs:** more interfaces (connectors) to define; the simulated rails must be visibly labeled to stay honest; arithmetic depends on OCR quality (low-confidence fields → "unreadable, pending", never "tampered").
- **Prototype reality:** the genuinely-buildable crypto/forensic core is substantial and real; only partner rails are simulated. The architecture demonstrated *is* the production architecture.

---

## Honesty caveats (do not assert as fact)
Several adoption stats in RESEARCH-001 are vendor-sourced; EU EUDI/provenance rails are pre-production; some claims were flagged OVERCLAIMED (e.g. "live capture has replaced uploads"; "NIST requires GenAI media analysis" — it's a SHOULD). See RESEARCH-001 §6.

*Constrained by [CLAUDE.md](../CLAUDE.md). Builds on [ADR-001](ADR-001-dual-mode-and-signal-validity.md).*
