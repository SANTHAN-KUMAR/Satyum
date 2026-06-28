# CLAUDE.md — Satyum Engineering Charter

> Operating contract for **every** agent and contributor in this repo. Read it fully before writing code.
> When in doubt, the rules here win over convenience, speed, or "making a demo look good."
>
> **Mindset:** We are building **production software for Canara Bank** — a document-fraud defense system
> real underwriters will rely on to approve real loans. Not a weekend hack. Treat every line as if it
> ships to a regulated financial institution and will be read, audited, and extended by other engineers.
> Engineering standards are constant; under a deadline only **scope** flexes — never **quality or integrity**.
>
> **Authoritative design** (read these): [ADR-001](architecture/ADR-001-dual-mode-and-signal-validity.md)
> → [ADR-002 provenance-first](architecture/ADR-002-provenance-first-verification.md) →
> [ADR-003 innovation thesis](architecture/ADR-003-innovation-thesis.md); grounded by
> [RESEARCH-001](architecture/RESEARCH-001-industry-landscape.md); built per
> [BUILD-MANIFEST](architecture/BUILD-MANIFEST.md). (`HIGH_LEVEL`/`LOW_LEVEL` docs are **superseded**.)

---

## 1. What we are building

**Satyum** (सत्यम् = *truth*) is a **real-time document-integrity evidence console** for bank underwriting.
It tells an underwriter **what changed, where, why it's risky, and what to do** — an explainable, auditable
trust score (0–100) + an **Underwriter Evidence Pack** — before a document informs a lending decision.

**At its core it is a cybersecurity system,** not a document-CV app: applied **cryptography + PKI**
(digital-signature verification, trust-chain validation, content provenance), **anti-spoofing / anti-injection**
capture security, a **threat-modeled fail-closed** pipeline, and a **tamper-evident audit** trail — wrapped
around the document-fraud use case. (SuRaksha *Cyber* Hackathon 2.0; the security spine must read as such.)

### Why we win — the innovation thesis (see [ADR-003](architecture/ADR-003-innovation-thesis.md))
Provenance/open-banking solve the *easy* (sourceable) document. The unsolved frontier — where GenAI forgeries
now win and pixel-forensics collapse — is the **un-sourceable document** (scanned paper, co-op/regional banks
off Account Aggregator, thin-file borrowers, wet-ink deeds, vernacular docs). Our novel, fully-real angle:
**a forger (human or AI) can fake the pixels but cannot keep the document's *logic* coherent.** We attack the
consistency layer, not pixels —
1. **Arithmetic / cross-field consistency** *(primary tamper signal)* — recompute every invariant; catches edits and incoherent GenAI output. Pure logic, zero fake AI.
2. **Active 3D challenge** — server-randomized physical challenge-response verified by homography (banks don't do this for docs).
3. **Cross-document consistency graph** — statement ↔ ID ↔ deed agreement across the bundle.
4. **Resubmission / fraud-ring memory (pHash)** — the same forged doc reused across applicants.

### The verification waterfall (provenance first → forensics → in-person)
Each detector runs ONLY in the mode where its signal physically exists; every signal is **mode-tagged**.
- **Tier 1 — Source-of-truth verification (first-line control), built for real, no partner.** Verify the
  document's **cryptographic signature** before trusting its bytes: PAdES/eIDAS verification (pyHanko) chaining
  to the public **CCA-India PKI** root — this covers **DigiLocker-issued docs, signed bank e-statements, and
  signed state land RoR/EC**; plus C2PA content-provenance (trust-list pinned). Pass → integrity answered at the
  root; fail → fail-closed. **A PDF-only submission when a source-pull was possible is itself a red flag.**
- **Tier 2 — Trusted forensic fallback (only when no verifiable source).** PDF metadata/structure anomaly,
  template fingerprinting, **OCR + arithmetic/cross-field consistency (primary)**, font/layout anomaly,
  copy-move, pHash. Industry-**distrusted** pixel forensics (ELA, PRNU, steganalysis, neural GradCAM) are
  **excluded / `NOT_EVALUATED`** — near-chance and they collapse on GenAI forgeries.
- **Tier 3 — Live capture (in-person escalation).** WebRTC camera for wet-ink/contested docs: rectify +
  quality-gate, the active 3D challenge (presentation-attack defense), anti-spoof votes, and a (low-weight,
  honestly-bypassable) virtual-camera/sensor-integrity check. Stops *presentation* attacks, **not injection**.

- **Client / theme:** Canara Bank · SuRaksha Cyber Hackathon 2.0 → Theme 1 (real-time document anomaly
  detection for underwriting). **Primary target document: financial statements.**
- **Identity (face-KYC) is a separate, consented mode.** rPPG/deepfake live there only, `NOT_EVALUATED` until
  validated, and **never feed the document trust score**. Micro-expression is **cut** (ethics/science).

**Mode-tagging invariant (integrity-critical):** a file-forensic signal can **never** display as "passed" on a
camera frame — it renders `NOT_EVALUATED`. The orchestrator enforces this structurally.

---

## 2. Engineering standard — timelines do not dictate quality

**Deadlines are not an engineering input.** Do **not** rush, cut corners, skip tests, downscope, or strip
features because a date is near. If there is genuinely not enough runway to build something to production
standard, ship it as an **honest, labeled stub** (§3.4) and keep the bar intact — never a half-wired feature
dressed up as working, and never delete an ambition because the calendar is loud.

**The only legitimate reason to defer/cut/relabel a capability is _merit_ — never the clock.** A signal is
dropped because first-principles analysis shows it is weak, unvalidated, unethical, physically inapplicable to
the medium (§3.1, §6), or **buildable-but-distrusted** — not because "we're short on time." "We ran out of days"
must never appear, explicitly or implicitly, in a commit, design doc, or comment.

**And honesty is never a cover for inability.** If a real, working version is genuinely buildable (even just a
crypto/parse with an open library), **build it** — do not hide behind `NOT_EVALUATED` or a "simulated connector."
A stub/simulation is permitted *only* where a real substitute does not exist (a regulatory credential or a
browser-medium limit), and it must be labeled with its precise gate (see [BUILD-MANIFEST](architecture/BUILD-MANIFEST.md)).

**Build order (by dependency, not calendar):** (1) a real end-to-end spine — intake → orchestrator → risk
score → evidence console, genuinely running; (2) deepen the signals confirmed real and survivable, to
production depth; (3) everything else is an explicit, labeled stub surfaced honestly in the UI.

**Assessed on** Problem Understanding · Originality · Technical Implementation · Real-World Applicability
(25 each) — each satisfied by *genuine engineering quality*, not demo theatrics. Build for the bank; the
rubric follows.

---

## 3. PRIME DIRECTIVE — Integrity of implementation and verification

> Satyum is a *fraud-detection* product. If our own code lies about what it detected, the project is
> self-defeating. **Honesty in code is the single non-negotiable rule of this repo.**

### 3.1 No fake signals
A function that claims to analyze something **must actually analyze it.** Its output must change when the input
changes in the way it claims to detect.
- ❌ `return 0.92` / `return random.uniform(...)` / a flow scripted to APPROVE regardless of input.
- ✅ Real computation that responds to real bytes (e.g. recompute the running balance and compare to the printed figure).

**Self-test before committing any analyzer:** *"If I fed this a deliberately tampered input, would its output
actually change? If not, it isn't analyzing anything — fix it or label it a stub."*

**Signals must be physically valid for the capture medium.** A webcam frame of *physical* paper carries **no
digital file edit history**, so file-level forensics (ELA, LSB/DCT stego, JPEG copy-move, GAN-frequency AI-gen)
have no signal there — shipping them on the camera path and calling them "working" is a fake signal. Use what
survives the medium (structural/semantic/perceptual/optical-physical or cryptographic); reserve bitstream
forensics for the real file path.

### 3.2 No shallow-proxy tests — EVER
A test must verify **real, discriminative behavior**, not trivia true regardless of correctness.
- ❌ `assert result is not None` · `isinstance(score, float)` · `0 <= score <= 100` · `len(flags) >= 0` · mocking the unit under test then asserting the mock · hardcoding expected = current output.
- ✅ Known-genuine → **passes**; known-tampered → **flagged**. Prove discrimination.

**Litmus:** *"If I replaced the implementation with `return <constant>`, would this test still pass? If yes, it's
a shallow proxy — rewrite it to fail against a constant."* Each real detector ships the **must-fail fixtures**
named in BUILD-MANIFEST (e.g. signature verification: a self-signed-cert PDF **and** an appended-bytes PDF must
both FAIL; arithmetic: a single-field edit must break an invariant). A passing suite that proves nothing is
worse than none — in a fraud system it means waved-through forgeries.

### 3.3 Never chase the result
Don't tune thresholds or edit expected values **just** to make one demo/test pass. A misclassified genuine
sample is a *finding* — investigate it. Report honest accuracy, never invented numbers.

### 3.4 The honest escape hatch — for genuine blockers only
When something genuinely cannot be built real (physics, ethics, a regulatory credential, a browser-medium
limit), return an explicit `NOT_EVALUATED` — never a fabricated pass — and label the precise reason.
```python
def verify_account_aggregator_pull(ctx) -> LayerSignal:
    # GATED: production AA live-pull needs RBI-regulated FIU onboarding. We DO verify the real
    # FIP-signed JSON; only live data *freshness* is gated. Never present fabricated data as live.
    return LayerSignal(status="NOT_EVALUATED", reason="AA production pull: FIU credential (regulatory)")
```
The risk engine excludes `NOT_EVALUATED` from the score; the UI shows it as **pending**, distinct from
pass/fail. A labeled gate costs us nothing with a bank; a fake "working" feature that breaks under one question
costs us trust. (But re-read §2: do not reach for this hatch when a real build is actually feasible.)

### 3.5 Report reality
"Done" means *built, run, and observed working* — not "looks like it should." State what works, what's stubbed,
what's untested. If it errored when you ran it, say so with the output.

---

## 4. Software system design principles

Design the system the way a bank's platform team would expect to inherit it.

- **Tiered orchestration, single-responsibility analyzers.** `app/` (routes + orchestrator) · `verification/`
  (Tier-1 crypto/provenance) · `forensics/` (Tier-2) · `capture/` (Tier-3 camera) · `risk/` (scoring + evidence
  pack) · shared `contracts`. Analyzers **never call each other** — the orchestrator runs the waterfall and
  composes results. Each analyzer does one job and returns one typed `LayerSignal`.
- **Program to contracts (Dependency Inversion).** The orchestrator depends on a stable `Analyzer` interface
  (`applicable(ctx) -> bool`, `analyze(ctx) -> LayerSignal`) bound to a `Mode`, via a **mode-keyed registry** —
  not on concrete OpenCV/pyHanko calls. Adding a signal must not edit the orchestrator core (Open/Closed); any
  analyzer is swappable (Liskov). The registry **structurally forbids** running a file-mode analyzer on a camera
  frame (the mode-tagging invariant).
- **Narrow, validated interfaces (Interface Segregation).** Validate everything crossing a trust boundary
  (uploaded files, WebSocket frames, API bodies) with Pydantic — reject malformed input loudly, early.
- **Fail safe / fail closed — the cardinal banking rule.** On any error, timeout, or uncertainty, degrade toward
  the *more secure* outcome: an analyzer that crashes returns `ERROR`/`NOT_EVALUATED`, never silent PASS; an
  indeterminate aggregate resolves to **REVIEW**, never auto-APPROVE. One analyzer's failure never crashes the
  verdict or the stream.
- **Deterministic & auditable by design.** The core is **classical CV + cryptography + logic — no black-box ML**
  in the decision path, so given the same input + config a verdict is reproducible and explainable down to the
  contributing signals (a defensibility win with a bank; see §11). No hidden randomness except the server
  challenge nonce (which is logged).
- **Resilience & graceful degradation.** Per-analyzer timeouts; isolate failures; bound queues and apply
  backpressure on the camera path (drop frames, never melt down).
- **Stateless & scalable.** Request processing stateless; session state in one swappable place (in-memory now,
  designed to move to Redis); scale by adding workers, not rewrites.
- **Observability + tamper-evident audit.** Structured logs with a **session/correlation ID** on every line;
  per-analyzer latency/outcome metrics; an **append-only, hash-chained audit trail** of every verdict and the
  signals behind it (banks must reconstruct *why* a decision was made — and prove the record wasn't altered).
  Never log customer document content or imagery (§10).
- **Configuration over hardcoding.** Thresholds, weights, trust anchors, cadence, endpoints live in config/env —
  one source of truth, environment values via `.env`, never committed.
- **Stable, versioned contract.** `LayerSignal` + the trust-score JSON are a published contract; evolve
  deliberately, keep frontend/backend in lockstep, document changes in `architecture/`.

---

## 5. Engineering & coding principles

Code is read far more than written — here, by Canara Bank's auditors.

- **Clean, intention-revealing names** (`recompute_running_balance`, not `process2`).
- **Small, single-purpose functions.** Pure analysis functions are **stateless, side-effect-free** (input → signal) — easier to test for real and to parallelize.
- **DRY but not prematurely abstract** (YAGNI); simplest design that meets the need (KISS); three real repetitions before an abstraction.
- **Explicit over implicit.** Type-hint all Python; validate at boundaries; typed results, not loose dicts in the hot path.
- **Immutability at boundaries.** Incoming files/frames are read-only; copy before mutating; no shared mutable state across sessions.
- **No magic numbers.** Every threshold/weight is a **named, configurable constant with provenance** — calibrated against real samples (record how) or marked `# DEFAULT — needs calibration`. Invented numbers presented as validated are a §3 violation.
- **Errors are loud and handled — never swallowed.** No bare `except:`; catch specific exceptions, log with context, degrade fail-safe (§4). An empty `except` that hides a signature-verification failure can wave a forgery through — forbidden.
- **Defensive at trust boundaries, trusting within.** Validate external input once at the edge; internal functions assume validated types.
- **Document the technique and its limits** in docstrings (e.g. "arithmetic consistency catches single-field edits, not a fully recomputed reprint"). Skip comments that restate code.
- **Tool-enforced formatting/linting** (ruff/black/mypy; eslint/prettier/tsc) — not by hand. Logging, never `print`.
- **Leave it cleaner.** No dead code, commented-out experiments, or debug scaffolding in commits.

---

## 6. Anti-hallucination protocol

Crypto + CV libraries make invented APIs the #1 source of broken code. Ground every claim.
1. **Verify the API before you call it** — confirm the signature in the installed version (`pip show`, read the module/official docs). Don't recall from memory. (Verified load-bearing facts: pyHanko custom `trust_roots`; `c2pa` cert-anchor verification; WebNFC is NDEF-only.)
2. **No phantom references.** Every import, function, cert, env var, path must exist or be created in the same change.
3. **Run it, don't imagine it.** Crypto/CV breaks in ways static reading misses (cert chains, `/ByteRange`, BGR vs RGB, dtype). Execute before claiming it works.
4. **Numbers need provenance** (§5).
5. **Cite real techniques only** — PAdES, C2PA, homography, ORB, pHash, running-balance arithmetic are real; keep implementations faithful. No invented pseudo-science.
6. **When unsure, say "unverified" and check.**
7. **Signal-medium validity first** — never implement a detector whose signal the capture path already destroyed (§3.1).

---

## 7. Performance & workload discipline

Mixed workload — design each path for its profile.
- **File path (primary): fast and synchronous-feeling.** Signature verification + PDF parse + OCR + arithmetic are CPU-bound, sub-second to a few seconds — run blocking work in an executor; keep `async` endpoints non-blocking. Cache trust anchors / loaded certs once at startup.
- **Camera path (escalation): real-time.** Process at a sane cadence (~300 ms windows), not every frame; downscale to the smallest size that preserves the signal; reuse buffers; **backpressure** — drop frames, never queue unboundedly.
- **Vectorize with NumPy**; avoid Python pixel loops. **Profile before optimizing** — measure, don't guess.
- Handle failure paths (unparsable PDF, no document in frame, dropped socket) — the system dies on unhandled edges.

---

## 8. Testing & verification standards

**Full adversarial regime: [TESTING-STRATEGY](architecture/TESTING-STRATEGY.md)** — discrimination tests, the constant-return guard, mutation testing, the per-tier attack matrix, fuzzing, chaos/fail-closed, and honest measured metrics. §3.2 governs *what* a good test is; this governs *how*.
- **Test each analyzer's discriminative claim** with a genuine-vs-adversarial pair, and ship the **must-fail fixtures** from BUILD-MANIFEST. Non-negotiable examples:
  - Signature verification: a PDF signed with an **attacker's own cert** → chain-to-anchor FAILS; a validly-signed PDF with **bytes appended after `/ByteRange`** → digest FAILS.
  - Arithmetic engine: genuine statement passes; **one altered figure breaks an invariant** and flags the exact cell; survives realistic OCR noise.
  - The injection/sensor check must **never** emit an unearned PASS.
- **Keep a small `tests/fixtures/` set** (genuine + tampered + screen-photo + signed + appended-bytes samples). No fixture hand-tuned until a test passes.
- **Integration-test the waterfall end-to-end** at least once: intake → orchestrator → trust-score JSON with the expected tier + verdict band.
- **Manual verification is part of "done"** for UI/stream work: open the app, run a real document, watch the evidence console (use the `/verify` or `/run` skills).
- Can't test something for real yet? Leave it untested **and say so** — never backfill a shallow proxy.

---

## 9. UI/UX standards — the Underwriter Evidence Console

The frontend is what the bank sees; it must look like a product Canara Bank would deploy.
- **Design language:** clean, professional, trust-conveying. Restrained palette (deep blue/slate + one accent), generous whitespace, strong type hierarchy. A "fintech security console," not a neon dashboard.
- **The console is the hero — explainability is the differentiator.** Per case, surface: **intake mode + document type**; the **provenance result** (signature valid / issuer / chain — or "no verifiable source"); the **verification tier reached**; **per-signal status with its producing-mode tag** (VALID / `NOT_EVALUATED`-pending / FAIL); the **deterministic tamper-evidence map** (only regions traced to a real detector — OCR-field anomaly, copy-move cluster, noise outlier; **never** a placeholder/GradCAM heatmap); the **arithmetic breakdown** showing exactly which invariant broke; and a **recommended action with reasons**.
- **Three honest verdict states**, unmistakable: ✅ APPROVED · ⚠️ REVIEW · ❌ REJECTED — plus a distinct **"not evaluated / pending"** treatment. Never a green pass for something that didn't run.
- **Trust score:** a clear gauge (0–100) with the threshold bands labeled.
- **Live camera mode:** overlay the active-challenge instruction and per-tier status as it happens, so the pipeline feels alive.
- **Responsive & accessible:** laptop + projector; sufficient contrast, keyboard-navigable, `aria` labels, visible focus, captioned camera-permission states.
- **Every state designed:** loading, no-camera, permission-denied, unparsable-file, processing, error — none left as a raw browser error.
- **No fabricated UI data.** Every number on screen comes from real backend output. No hardcoded "87%".

---

## 10. Security engineering, privacy & compliance (it's a *Cyber* hackathon — live it)

This is the cybersecurity spine; treat these as features, not hygiene.
- **Applied cryptography / PKI is core, done right.** Signature verification must validate the full chain to a
  pinned trust anchor (CCA-India / CA roots), check `/ByteRange` coverage, revocation (CRL/OCSP), and embedded
  timestamps. **Defend the real PDF-signature attack classes** — "signature exists" is not "signature valid";
  detect **incremental-update / shadow-attack** tampering after signing. C2PA must pin a trust list (an unpinned
  manifest is the documented self-signed exploit). **Fail closed** on any unverifiable element.
- **Safe file ingestion (file mode is the primary path).** Parse untrusted PDFs/images defensively: size/type
  limits, disable external entity / JS execution, sandbox parsing, never shell out to a renderer on raw input.
  Treat every uploaded file as hostile.
- **Tamper-evident audit & non-repudiation.** Verdicts and their signals go to an **append-only, hash-chained**
  log so a decision can be reconstructed and proven un-altered.
- **Privacy by design (the hackathon's other theme).** Camera frames live in memory for the session only and are
  **never persisted**; no frame logging or debug image dumps. **Redact PII** before anything is logged; encrypt
  the fraud-hash DB at rest; the face-KYC mode runs only under explicit **DPDP consent**.
- **No secrets, private keys, or real customer data in git.** Gitignored `.env`; ship only public trust roots and synthetic samples.
- **Validate and rate-limit** all endpoints; one session token per verification; the server challenge is a time-bounded nonce (anti-replay).
- **Threat-model the system** (replay, screen-spoof, injection, tampered upload, signature-stripping, resubmission) and keep the model in `architecture/` — banks value this artifact.

---

## 11. Tech stack & conventions — defensible, survivable, not a demo dummy

Chosen so the prototype *is* the production architecture. Rationale: the decision path is **deterministic
(classical CV + cryptography + logic), with no PyTorch/black-box model in the core** — lighter, faster, fully
auditable and reproducible, no GPU or model-weights dependency. That determinism is itself a security argument.

| Area | Choice | Why |
|---|---|---|
| **Backend** | Python 3.11+, **FastAPI** + Uvicorn (async), **Pydantic v2** | The crypto/forensic ecosystem is Python; typed contracts at every boundary |
| **Crypto / provenance** | **pyHanko** (PAdES/CMS, custom `trust_roots` = CCA-India PKI), `cryptography`, `asn1crypto`; **c2pa** (trust-list pinned) | Real signature + content-provenance verification, offline, no partner |
| **PDF / parse** | **pikepdf** (qpdf) + **PyMuPDF** (fitz) | Structure/metadata forensics + safe render; defensive parsing |
| **OCR** | **Tesseract** (`pytesseract`) for the prototype; PaddleOCR as the vernacular/land-record upgrade | Deterministic, deployable; no heavy ML dep by default |
| **CV / hashing** | **OpenCV** + NumPy + scikit-image + Pillow; **imagehash** (pHash) | Rectify, homography challenge, copy-move (ORB+RANSAC), anti-spoof FFT, perceptual hash |
| **Consistency engine** | Pure Python (`Decimal`) | The primary tamper signal — exact arithmetic, fully auditable |
| **Data** | **PostgreSQL** (fraud-hash DB, hash-chained audit, issuer-capability registry, template corpus) via SQLAlchemy 2.0 + Alembic; **in-memory** ephemeral session/frames (never persisted) | Real durable store; privacy-preserving session handling |
| **Frontend** | **React 18 + TypeScript + Vite**, **Tailwind CSS + shadcn/ui** (Radix), WebRTC + native WebSocket, TanStack Query | Accessible, production-grade, typed evidence console — not a template dummy |
| **Infra** | **Docker** + docker-compose, **Nginx** (TLS + reverse proxy `/api` `/ws` `/`), 12-factor env, **structlog** + correlation IDs, healthchecks | Reproducible, observable, deployable |
| **Quality/CI** | pytest (+ must-fail fixtures), ruff/black/mypy; vitest + Playwright, eslint/prettier; pre-commit; CI gate runs the must-fail fixtures | Enforces §3/§8 mechanically |
| *(deferred)* | PyTorch/MediaPipe **only** if the face-KYC mode is later built — not in the document path | Out of the core on purpose |

- **Shared contract:** `LayerSignal` (`name`, `layer`, `mode`, `status`, `suspicion`, `weight`, `reason`,
  `evidence_regions`, `measurements`, `producing_mode`) and the trust-score JSON (`session_id`, `intake_mode`,
  `doc_type`, `provenance`, `trust_score`, `verdict`, `signals`, `evidence_pack`, `fail_closed`). Keep
  frontend/backend in lockstep.
- **Pin dependencies** (lockfiles) for reproducible builds; keep `.env.example` current; no hardcoded URLs/ports.

---

## 12. Workflow, housekeeping & technical-debt discipline

- **Branching/commits:** don't commit or push unless asked. If asked, branch off `main` first; honest commit messages describing what actually changed (and what's still gated).
- **Technical debt is recorded, never hidden** — `TODO(owner): reason + intended fix`; behavioral debt noted in the PR/handover. Silent debt forbidden.
- **Keep docs true:** changing the architecture or contract → update `architecture/` (the relevant ADR) in the same change.
- **Scratch files** go in the session scratchpad, not the repo.
- **Before marking a task done, run §13.**

---

## 13. Definition of Done

A change is done only when **all** hold:
- [ ] It **runs** — you executed it (unit, or the app end-to-end) and observed real behavior.
- [ ] Every analyzer **responds to input** (passes the §3.1 self-test) or is an **honestly-labeled gate** (§3.4) — and isn't a real-build dodged behind a stub (§2).
- [ ] Tests assert **real discriminative behavior**, would **fail against a constant**, and the **must-fail fixtures** pass (§3.2, §8).
- [ ] Design holds: mode-tagged, programs to contracts, **fails safe/closed**, no analyzer can crash the verdict (§4).
- [ ] Security: signatures validated to a pinned anchor (not "exists"); untrusted files parsed defensively; verdict written to the tamper-evident audit (§10).
- [ ] Clean code: named constants with provenance, specific error handling, typed boundaries, linted (§5).
- [ ] No phantom imports/paths/certs; numbers have provenance or a calibration note (§6).
- [ ] UI shows only **real backend data**, handles failure states, distinguishes pass / fail / not-evaluated (§9).
- [ ] No customer document content or frames persisted; PII redacted from logs; no secrets/keys committed (§10).
- [ ] Any shortcut is a **recorded** TODO, not hidden debt (§12); you **reported honestly** what works, what's gated, what's untested.

> If you're tempted to skip one of these to save time, that's exactly the moment this file exists for.
> **Ship less, real — never more, faked.** We are handing this to a bank.
