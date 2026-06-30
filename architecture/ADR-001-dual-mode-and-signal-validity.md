# ADR-001 — Dual-Mode Intake, Signal-Medium Validity, and the Underwriting Evidence Console

> **Still in force.** Built on by [ADR-004](ADR-004-v2-progressive-evidence-architecture.md) (the v2 architecture of record). Mode-tagging / provenance-first / fail-closed carry into v2 unchanged.

> **Status:** Accepted · 2026-06-27 · **evolved by [ADR-002](ADR-002-provenance-first-verification.md)** (provenance-first verification waterfall, grounded by [RESEARCH-001](RESEARCH-001-industry-landscape.md))
> **Supersedes:** the camera-only design in [HIGH_LEVEL_ARCHITECTURE.md](HIGH_LEVEL_ARCHITECTURE.md) and [LOW_LEVEL_ARCHITECTURE.md](LOW_LEVEL_ARCHITECTURE.md)
> **Scope:** Satyum — SuRaksha Cyber Hackathon 2.0 (Canara Bank), Theme 1 (real-time anomaly detection in financial documents for underwriting)
>
> This ADR is the **authoritative architecture** going forward. Where the older docs disagree, this wins.

---

## Context

The original design was a **zero-trust, camera-only** platform: the customer holds a physical document to a webcam, and a 5-layer pipeline (12 "signal-intelligence" detectors) issues a trust score. An external critique challenged the scope and several signals. We validated every claim with a first-principles, adversarially-verified analysis (physics of optics/compression, signal processing, ML data requirements, statistics, ethics/regulation). The analysis confirmed **~85–90% of the critique on the merits** and surfaced one finding that reshapes the architecture.

**This is a merit-driven re-architecture, not a deadline-driven downscope** (see [CLAUDE.md §2](../CLAUDE.md)). Nothing here is cut "for time"; every change follows from physics, science, ethics, or theme-fit.

---

## The core finding

> **Camera capture and file-level digital forensics are mutually exclusive.** A webcam frame of a *physical* document is light reflected off paper, printed (halftone + ink spread), imaged through a Bayer sensor (demosaic invents pixel LSBs), and encoded by a **video** codec (VP8/VP9/H.264 — inter-frame prediction, adaptive per-block quantization, in-loop **deblocking** that erases block-grid discontinuities). This chain is *designed* to preserve only what a human must read — glyphs, numbers, layout — and to discard exactly the bit-level artifacts (JPEG quantization history, LSB planes, 8×8 block grids, GAN frequency fingerprints) that ELA, steganalysis, JPEG copy-move, and AI-gen detectors depend on.

Consequence: the original Layer 3 pointed file-forensic detectors at a medium that had already destroyed their signal. Running them on camera frames produces **confident-looking but content/codec-driven output that does not change with tampering** — a fake signal by our own definition ([CLAUDE.md §3.1](../CLAUDE.md)).

---

## Decisions

### D1 — Dual-mode intake (was: camera-only)
- **File-input mode = default, primary path.** The dominant underwriting input (land records, legal docs, financial statements) is native digital files, frequently cryptographically signed (Account Aggregator FIP-signed JSON, DigiLocker issuer-pull, born-digital PDFs). A webcam cannot honestly ingest these — displaying a PDF on a screen is exactly what anti-spoof must *reject*, and print-recapture destroys the file's forensic evidence.
- **Live-capture mode = escalation path** for in-person, wet-ink originals, and contested/high-risk cases — where live capture + the active physical challenge are physically meaningful and genuinely original.

### D2 — Mode-tagging invariant (integrity-critical)
Every detector declares the **one mode** it may run in. Every `LayerSignal` is tagged with its producing mode. **A file-forensic signal can never be displayed as "passed" on a camera frame** — it renders `NOT_EVALUATED` instead. The orchestrator enforces this structurally (mode-keyed analyzer registry); a meta-test asserts the invariant.

### D3 — Provenance-first short-circuit
If a document arrives signed (AA / DigiLocker / PAdES), **verify the cryptographic signature first.** Integrity is then answered by crypto, not CV; forensic detectors return `NOT_EVALUATED("provenance-trusted")`. A broken signature fails closed to REVIEW/REJECT.

### D4 — Re-center Layer 3 (camera) on structural/semantic forensics
The only thing that survives the analog hole is high-energy semantic/geometric content. Camera Layer 3, in dependency order:
1. **Rectify + quality gate** — boundary detect → perspective correct → blur/lighting/resolution gate (fail-closes to REVIEW on poor capture). *Foundation for everything downstream.*
2. **OCR field extraction** — account numbers, balances, names, dates, parcel IDs (per-field bbox + confidence). *Produces the underwriting inputs.*
3. **Cross-field / arithmetic-consistency engine** — `subtotal = Σ line items`, balance carry-forward, `debits = credits`, declared vs computed income/tax. **The primary in-document tamper signal:** edit one printed number and at least one invariant breaks; it survives the camera because it operates on *read numbers*, not pixels. *Caveat: catches single-field edits, not a fully recomputed-and-reprinted forgery — pHash resubmission + external cross-reference cover that gap.*
4. **Font / layout / alignment anomaly** — per-glyph geometry outliers (baseline, stroke-width, x-height, kerning), surfaced as evidence-with-confidence, not a binary gate.
5. **Spatial copy-move** — ORB + RANSAC matched-offset clustering, with guards against legitimately repeated structure (gridlines, logos, identical glyphs). Low weight.
6. **pHash resubmission** — perceptual hash of the rectified crop vs a fraud-hash store; Hamming threshold from a validated ROC.

### D5 — Active 3D challenge is the anti-spoof centerpiece
Server-randomized tilt/rotate/proximity command, verified by corner tracking + per-frame homography consistency. A replay can't satisfy an unpredictable just-issued command; a photo-of-screen exposes a bezel/double-perspective that breaks single-homography consistency. **Model-free, passes the discrimination self-test hard, and survives the held-phone attack** that defeats micro-tremor. Frame as *raising attacker cost*, not unbeatable. Layer-1 anti-spoof (merged moiré/paper-texture spectral, specular, temporal-entropy) are contributing **votes**, never hard gates.

### D6 — Replace neural GradCAM with a deterministic tamper-evidence map
GradCAM is meaningless without a forgery classifier trained *and validated on this exact webcam+codec distribution*, which does not exist. The explainability heatmap is composited **only** from real detector outputs (OCR field anomaly + copy-move clusters + coarse noise-residual outliers) — every highlighted region traces to a measurement.

### D7 — Underwriter Evidence Pack as a first-class Layer-5 output
Per case: doc type + intake mode, provenance result, OCR-extracted fields, **per-signal score with status (VALID / NOT_EVALUATED) and producing mode**, the real tamper-evidence map, aggregate risk with weighted explanation, **recommended action**, and an ephemeral-handling note. This serves the theme's second clause — "intelligent insights for faster, reliable underwriting decisions."

### D8 — Locked product decisions (user, 2026-06-27)
- **Primary document type: financial statements** (unlocks the arithmetic engine — strongest, most demoable tamper signal). Land records/legal docs lean on layout + provenance + pHash.
- **Identity is a separate, consented face-KYC mode.** rPPG + deepfake live there only, `NOT_EVALUATED` until validated on the real capture distribution, with DPDP consent — and they **never feed the document trust score**.
- **Positioning: a real-time underwriting *evidence console*** — "what changed, where, why it's risky, what action to take" — leading with the behavioral active-challenge and ephemeral/zero-retention privacy angles (which also align with the hackathon's broader behavioral-auth + data-privacy vision).

---

## Signal disposition (full)

| Signal | Decision | Merit reason |
|---|---|---|
| Active 3D challenge (homography-verified) | **KEEP — centerpiece** | Model-free, physically valid, survives held-phone attack |
| Rectify + quality gate | **KEEP — foundation** | Deterministic prerequisite for all camera signals |
| OCR + arithmetic/cross-field consistency | **KEEP — primary Layer 3** | Survives the medium; true single-field tamper signal |
| Font/layout anomaly · spatial copy-move · pHash | **KEEP (fix)** | Survive the medium; RANSAC + repetition guards + ROC threshold |
| Moiré / paper-texture FFT | **KEEP (fix)** — merge into one spectral *vote* | Real but confoundable; never a hard gate |
| Specular/glare · temporal frame entropy | **KEEP (fix)** | Votes; temporal-entropy (not single-frame spatial) for anti-replay |
| Optical flow | **KEEP (fix)** — tracking engine only | Drop the "physiological liveness" framing |
| Angular jerk | **KEEP (fix)** — low-weight **anti-scripted-motion** | Honest framing; not anti-screen-spoof |
| Ephemeral/zero-retention privacy · fail-closed semantics | **KEEP** | Genuine differentiator + DPDP fit |
| Micro-expression "stress"/AU deception | **CUT entirely** | Scientifically near-chance; off-theme; emotion inference restricted (EU AI Act/GDPR/DPDP), biased |
| Micro-tremor (as anti-replay) | **RELABEL `NOT_EVALUATED`** | Tremor is in the hand → a held phone reproduces it; doesn't discriminate |
| AI-gen frequency detector · neural GradCAM · noise-residual/PRNU (camera) | **RELABEL `NOT_EVALUATED`** | HF fingerprint destroyed / no validated model / single-camera overwrites PRNU |
| Hologram retroreflection · microprinting | **RELABEL `NOT_EVALUATED`** | Passive webcam can't excite OVD; microprint below sensor resolving power |
| ELA · LSB/DCT steganalysis · JPEG-domain copy-move | **MOVE → file mode** | Need bitstream artifacts that the camera erases; valid on native files |
| rPPG · deepfake | **MOVE → separate face-KYC mode** | Can't change with document tampering → fake signal if scored into document trust |

---

## Consequences

- **Positive:** every signal now runs where it is real; the product covers the dominant (file) input *and* keeps the original (camera) differentiator; the Evidence Pack directly serves the theme; the integrity posture is airtight (no faked passes, mode-tagged, fail-closed).
- **Costs / risks:** more surface than camera-only (two intake paths); the active-challenge robustness *is* the originality bet (mitigate: quality gate fail-closes to REVIEW, not REJECT; tune to real human samples); arithmetic engine depends on OCR (low-confidence fields render "unreadable — pending," never "tampered").
- **Scope still open (not blocking):** how deep to build file-mode bitstream forensics now vs. ship the provenance short-circuit + OCR/structural first and defer the rest as honest `NOT_EVALUATED` stubs. Camera-path file-forensics stay forbidden regardless.

---

## Honesty caveats (do not assert as fact in the pitch)
- The **4×25 prototype rubric** is taken from our official problem statement (primary source), but could **not** be corroborated online — confirm with organizers.
- **Theme wording:** web sources surfaced the hackathon's broader "behavioral authentication + data privacy" framing (and may conflate the 2025 edition). Our official problem statement lists document anomaly detection as a theme — that is our ground truth; a quick organizer confirmation is cheap insurance.
- Do **not** cite "RiverAuth was a finalist" or "winners were judged on encryption/tokenization/deployability" — unverified. (The 2025 funnel of 63 prototypes → 10 finalists and **Pindrop**'s 2nd prize *are* corroborated.)

---

*See [CLAUDE.md](../CLAUDE.md) for the engineering charter that constrains every implementation choice above.*
