# ADR-003 — Innovation Thesis: Consistency-First Defense for the Un-sourceable Document

> **Amended by [ADR-004](ADR-004-v2-progressive-evidence-architecture.md).** The consistency thesis stands and is now v2's Layer 4 (deterministic rules over a claim graph). The "no-ML-anywhere / no black-box model" commitment is narrowed to: no ML in the *decision* path — a VLM *reads* arbitrary layouts into a claim graph, deterministic rules *decide*, and every VLM number is box-grounded + independently re-read. See ADR-004 §0, §5, §9.

> **Status:** Accepted · 2026-06-28 · builds on [ADR-002](ADR-002-provenance-first-verification.md)
> **Grounded by:** [RESEARCH-001](RESEARCH-001-industry-landscape.md)
> This is *why Satyum wins* — the locked, defensible, genuinely-novel core. Not positioning; an engineering thesis.

---

## The gap (where the real fraud gets through)

Provenance and open-banking **solve the easy case**: a born-digital, signed, or source-pullable document. The **unsolved** problem — where fraud actually succeeds in Indian underwriting today — is the **document with no verifiable digital source**:

- scanned paper; statements from co-operative / regional / small-finance banks not on Account Aggregator;
- thin-file and self-employed borrowers; wet-ink land deeds; vernacular / regional-format documents.

This is exactly where **GenAI forgeries now win** — RESEARCH-001 found classical pixel forensics *collapse* on AI-generated documents (TruFor AUC 0.96 → 0.751), and practitioners already distrust ELA/PRNU (≈ chance). Everyone is racing to build better pixel detectors for a layer that is losing. **That gap is our innovation space.**

## The core insight (real and novel)

> A forger — human *or* a GenAI model — can produce a **pixel-perfect** fake document, but **cannot keep its internal logic coherent.** Balances don't carry forward, subtotals don't sum, declared income ≠ computed income, the statement's name/address doesn't match the ID or the deed, and the same forged artifact resurfaces across applications.

So Satyum attacks **a different layer than everyone else**: not the pixels, but the **consistency** a forger can't fake —

1. **Arithmetic / cross-field consistency** *(primary signal)* — recompute every in-document invariant (`subtotal = Σ lines`, balance carry-forward, `debits = credits`, declared vs computed income). Catches single-field edits **and** incoherent GenAI output that pixel detectors miss. Pure arithmetic + logic — zero fake AI.
2. **Active 3D challenge** — server-randomized physical challenge-response verified by homography. Banks do **not** do this for documents; a replay can't satisfy an unpredictable just-issued command. Real and creative.
3. **Cross-document consistency graph** — does the financial statement's identity agree with the ID and the land record across the application bundle?
4. **Resubmission / fraud-ring memory (pHash)** — catch the same forged document laundered across applicants/sessions.

All surfaced in **one explainable Underwriter Evidence Console** — *what changed, where, why it's risky, what to do next* — which banks do not have unified today.

## Why this wins all four criteria
- **Problem Understanding:** targets the actual unsolved frontier (un-sourceable docs, GenAI forgery), not the already-solved sourceable case.
- **Originality:** consistency-as-a-tamper-signal + physical challenge + cross-doc graph is a fresh angle on the *newest* threat — not "what banks already have."
- **Technical Implementation:** every pillar is fully real (arithmetic, geometry, hashing, crypto) — no black-box model to fake.
- **Real-World Applicability:** runs on a normal upload + webcam, deployable, privacy-aware, and produces an auditable underwriter decision.

## Honest bound (this is *why* it's defense-in-depth, not a silver bullet)
Consistency catches *incoherent* forgeries (casual edits, most GenAI output, sloppy template tools) — **not** a perfectly recomputed-and-reprinted forgery. That residual is covered by the **other** tiers: cryptographic provenance (ADR-002), the resubmission memory, the cross-document graph, and the physical challenge. Each layer covers another's gap — a more credible story to a bank than "one magic detector."

## What this commits us to
- The **consistency engine is the primary tamper signal**, built to production depth with an adversarial test matrix (BUILD-MANIFEST).
- The four pillars + the evidence console are **first-class**, not nice-to-haves.
- We do **not** invest in pixel/ML forgery detection that is dying and fakeable.

*See [CLAUDE.md §1](../CLAUDE.md). Constrained by the integrity charter (CLAUDE.md §3).*
