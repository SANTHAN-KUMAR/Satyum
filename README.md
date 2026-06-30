# 🔐 Satyum — सत्यम् (*truth*)

### A real-time document-integrity evidence console for bank underwriting

> **SuRaksha Cyber Hackathon 2.0 · Canara Bank · Theme 1** — real-time anomaly detection in financial
> documents. Built as production software for a regulated lender, not a demo.

Satyum tells an underwriter **what changed in a document, where, why it's risky, and what to do** —
an explainable, auditable **trust score (0–100)** and an **Underwriter Evidence Pack** — *before* the
document informs a lending decision. At its core it is a **cybersecurity** system: applied
cryptography/PKI, anti-spoofing capture security, a threat-modelled fail-closed pipeline, and a
tamper-evident audit trail, wrapped around the document-fraud use case.

---

## The idea in one line

> **The model *reads*; deterministic rules *decide*.** A forger can fake a document's pixels, but
> cannot keep its *logic* coherent — and that logic is judged by rules, never by the model.

Provenance and open-banking already solve the *sourceable* document. The unsolved frontier — where
GenAI forgeries now win and pixel-forensics collapse — is the **un-sourceable** document (scanned
paper, co-op/regional statements, thin-file borrowers, wet-ink deeds). The deterministic
consistency engine that attacks this — recomputing a document's logic instead of guessing its
pixels — was always the crown jewel; v1's real weakness was a **template-brittle parser** that
could only feed it one hardcoded statement layout. **v2 widens the mouth without softening the
judgment:** a vision-language model (VLM) *reads* arbitrary layouts into a **canonical claim graph**,
and the decision path stays deterministic, auditable, and fail-closed — now operating on normalised
claims instead of one fixed template. The VLM is an **untrusted, box-grounded, cross-verified input;
it never judges** (see [ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md) §5).

1. **Domain rule packs over the claim graph** *(primary signal)* — the financial pack recomputes
   every invariant (running balance, totals, net reconciliation, salary/income reconciliation); a
   single edited figure breaks the maths and is localised to the exact cell. Real land/title and
   legal/contract packs are **real-but-scoped** (every uncovered invariant returns `NOT_EVALUATED`,
   never a faked pass). Pure `Decimal` logic — the judgment is ML-free.
2. **VLM understanding, deterministically guarded** — every numeric claim is **independently
   re-read by a deterministic OCR** on its exact crop; the two must agree within tolerance or the
   claim is `NOT_EVALUATED`. This neutralises hallucination-laundering and prompt injection
   structurally — the number's authority comes from grounded, re-verified transcription, not the
   model's "understanding."
3. **Cross-document / cross-source corroboration** — the same identity (PAN/Aadhaar/name/DOB…) must
   agree across the statement ↔ ID ↔ deed bundle, and income claims must reconcile across
   statement ↔ salary slip ↔ Form-16/ITR; a hard mismatch is near-dispositive.
4. **Resubmission / fraud-ring memory** — perceptual hashing catches the same forged doc reused.
5. **Active 3D challenge** — for wet-ink / contested *physical* documents, a server-randomised
   physical tilt verified by homography (a flat screen-replay can't satisfy it), re-scoped to the
   in-person escalation path.

## The pipeline (provenance first → understanding → judgment → in-person)

A progressive-evidence waterfall: verify what can be verified, read what can't, judge with
deterministic rules, corroborate across the bundle, and **fail closed** when evidence is
insufficient. Every signal is **mode-tagged** and runs only where its evidence physically exists (a
file-forensic signal can never show "passed" on a camera frame). The three tiers of *trust* are
structurally separated: **source-of-truth** (authoritative), **understanding** (untrusted, grounded),
**judgment** (deterministic authority) — see [ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md) §2.

| Layer | Trust posture | What runs |
|---|---|---|
| **1 · Source of truth** *(authoritative)* | fully deterministic | **PAdES/CMS signature** verification chaining to a pinned PKI root (pyHanko) — a signature counts only when `intact ∧ valid ∧ trusted ∧ coverage == ENTIRE_FILE`, catching attacker-cert chains and appended-byte/shadow attacks — plus **C2PA** content-provenance (trust-list pinned). Verified = byte-authenticity, **not** claim-truthfulness, so verified claims still flow into corroboration (no over-short-circuit). |
| **2–3 · Understanding** *(untrusted input)* | probabilistic, *bounded* | A **VLM reads arbitrary layouts** → typed fields/tables, each with `page + bbox + confidence`, into a **canonical claim graph**. Every numeric claim is independently re-read by deterministic OCR (the demoted Tesseract table-parser) and must agree, or it is `NOT_EVALUATED`. The VLM has **zero decision authority**. |
| **4 · Judgment — rule packs** *(deterministic)* | fully deterministic | **Domain ontology + rule packs over the claim graph**: financial (production-depth — running balance, totals, net + salary/income reconciliation), land/title and legal/contract (real-but-scoped). Each rule returns `PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NOT_EVALUATED`. |
| **5 · Anomaly (hybrid, soft)** | stats deterministic; ML lane off by default | A deterministic statistical backbone (round-number synthetic credits, salary jumps, cherry-picked windows) + an **optional, flag-gated, experimental ML lane**. **REVIEW-only** — anomaly can raise review, never approve or reject. |
| **6 · Corroboration** *(deterministic)* | fully deterministic | Cross-document / cross-source: identity must agree across statement ↔ ID ↔ deed; income across statement ↔ salary slip ↔ Form-16/ITR; perceptual-hash resubmission memory. Single doc / no overlap → `INSUFFICIENT_CORROBORATION` → REVIEW. |
| **7 · Decision brain** *(deterministic, fail-closed)* | fully deterministic | A guarded policy engine → **APPROVE / REVIEW / REJECT / PENDING**, with the golden-rule guards as structural invariants (VLM alone can never approve; arithmetic-clean alone ≠ genuine; anomaly alone can never reject; missing evidence never becomes a pass). |
| **Interpretability** *(downstream, read-only)* | explains, never decides | A **narrator** turns the finished evidence pack into a 3-paragraph plain-English summary, and an **underwriter copilot** answers follow-up questions via MCP-style read-only tools over the *frozen* pack. A **firewall** discards any narrative that contradicts the verdict and always shows the true one; on any LLM failure it falls back to a deterministic narrative. The interpreter is decoupled from the vision reader (a text reasoner can narrate while a separate VLM reads). See [ADR-006](architecture/ADR-006-interpretability-and-resilience.md). |
| **In-person escalation** | mode-tagged | WebRTC capture for wet-ink / contested *physical* documents: rectify + quality gate, the **active 3D challenge**, anti-spoof votes (moiré/specular/temporal). Stops *presentation* attacks; injection is a documented, low-weight gate. |

### What we deliberately DON'T do (and why)

Honesty is a feature here. Industry-**distrusted**, near-chance, or unvalidated techniques are
**excluded or `NOT_EVALUATED`**, never faked into a green pass: **ELA, PRNU, LSB/DCT steganalysis,
neural GANs/GradCAM heatmaps** (collapse on GenAI forgeries — the VLM is an *understanding* layer,
**not** a pixel-forgery detector, so this exclusion stands), and **rPPG / micro-expression / deepfake**
(belong only to a separate, consented face-KYC mode — they **never feed the document score**). And
the model that reads never decides: **no ML/VLM sits in the decision path.** Determinism runs
**from the claim graph onward** — given the same claim graph and config, a verdict is reproducible
and explainable down to the contributing signals; the VLM extraction is bounded by box-grounding +
numeric cross-read, and the self-hosted production path (Qwen2.5-VL pinned in-perimeter) restores
full extraction reproducibility too.

### Real-world ingestion resilience (see [ADR-006](architecture/ADR-006-interpretability-and-resilience.md))

Real government/bank documents are messy; the pipeline handles that honestly rather than failing closed
on legitimate inputs:

- **Password-protected PDFs.** Aadhaar PDFs, CAMS/Karvy CAS, and signed bank e-statements ship
  encrypted. Satyum **detects** encryption and returns a recoverable *password-required* response (not a
  fraud signal, not an error); the applicant enters the password in-app and the backend **decrypts in
  memory** at every consumer, never re-saving. This **preserves the digital signature** — a 3rd-party
  "remove password" tool re-saves the file and destroys it; in-memory decrypt keeps it intact (verified
  end-to-end). The onboarding flow collects the password inline and resubmits.
- **Misparse-resistant arithmetic.** When the deterministic text-layer fallback misreads a balance cell
  (e.g. a stray `1` amid lakh-scale balances), a plausibility / cross-read gate drops the off-scale
  figure instead of cascading it into a false REJECT — an all-misparse break resolves to
  `NOT_EVALUATED` (pending → REVIEW), while a *plausible* edited figure (a real tamper) still flags.

---

## Repository layout

```
Satyum/
├── architecture/            ← the authoritative design (read these)
│   ├── ADR-004              ← v2 architecture of record (VLM reads · rules decide)
│   ├── ADR-005              ← federated fraud intelligence (consortium roadmap)
│   ├── ADR-006              ← interpretability layer · password-PDF decrypt · arithmetic misparse gate
│   ├── ADR-001 … ADR-003    ← dual-mode · provenance-first · innovation thesis (built on)
│   ├── RESEARCH-001         ← industry landscape grounding
│   ├── BUILD-MANIFEST.md    ← what's real / gated, with must-fail fixtures
│   └── TESTING-STRATEGY.md  ← the adversarial test regime
├── backend/                 ← FastAPI; provenance + claim-graph + deterministic decision core
│   ├── app/                 ← routes + orchestrator + mode-keyed registry + contracts (+ claim graph, VLMExtractor / AnomalyDetector / rule-pack interfaces)
│   ├── verification/        ← source-of-truth crypto/provenance (PAdES, C2PA) + in-memory password-PDF decrypt
│   ├── forensics/           ← rule packs (arithmetic → financial pack, w/ misparse cross-read gate), OCR cross-read verifier, metadata, copy-move, pHash, cross-doc, entities
│   ├── interpretability/    ← read-only narrator + underwriter copilot (MCP-style tools), firewalled off the verdict
│   ├── federation/          ← consortium ring detection / fraud-hash registry / advisory firewall (ADR-005)
│   ├── providers/           ← source-of-truth providers (Aadhaar offline e-KYC, PAN, DigiLocker, Account Aggregator)
│   ├── capture/             ← in-person escalation camera (active challenge, anti-spoof, rectify)
│   └── risk/                ← scoring + evidence pack + hash-chained audit ledger
├── frontend/                ← React 18 + TS + Vite + Tailwind — the evidence console
├── samples/                 ← synthetic drag-and-drop test corpus + generator + manifest
├── scripts/verify-satyum.sh ← one command: run the whole suite + regenerate samples
└── DEPLOY.md                ← Vercel (frontend) + Railway (backend) deployment guide
```

---

## Quick start

**Backend** (from `backend/`, Python 3.11+, system `tesseract-ocr` installed):
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# Point source-of-truth verification at the demo trust anchor so the sample signed PDF verifies:
SATYUM_TRUST_ANCHOR_DIR="../samples/trust" uvicorn app.main:app --reload
```
> **VLM understanding (Layer 2) is a config-driven dependency.** Per
> [ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md) §7 the `VLMExtractor`
> interface takes a **cloud VLM API key** for the POC (e.g. `ANTHROPIC_API_KEY`) and swaps to a
> **self-hosted vLLM endpoint serving Qwen2.5-VL** in production — a config/env change, no rewrite.
> The reader is **provider-agnostic**: alongside the native anthropic / gemini / groq readers, one
> OpenAI-compatible extractor (`SATYUM_VLM_BASE_URL`, plus `SATYUM_VLM_CLOUDFLARE_ACCOUNT_ID` for
> Workers AI) serves **Cloudflare Workers AI, OpenRouter, Together, DeepInfra, Fireworks, and local
> Ollama** — all behind the same box-grounded, cross-read trust boundary. (Cloudflare/Mistral-Small
> works for short docs; dense multi-page statements want a higher-throughput reader — Gemini / Claude /
> self-hosted Qwen2.5-VL.) The **interpretability** narrator/copilot can run on a *separate* text
> reasoner (`SATYUM_INTERPRET_*`, e.g. DeepSeek v4) — unset → it reuses the reader credential. See
> [`DEPLOY.md`](DEPLOY.md) for the env contract.

**Frontend** (from `frontend/`, Node 18+):
```bash
npm install && npm run dev      # proxies /api and /ws to the backend
```

**Try it** — open the app and drag files from [`samples/`](samples/README.md):
- **File upload** tab → `samples/pdfs/*` (signed / attacker / shadow-attack / unsigned) and
  `samples/statements/*` (genuine vs one-figure-tampered).
- **Document bundle** tab → both files in `samples/bundle_consistent/` (corroborates) or
  `samples/bundle_mismatch/` (hard PAN mismatch → rejected).

Each sample's expected verdict is documented in [`samples/README.md`](samples/README.md).

## Verify the whole system in one command

```bash
./scripts/verify-satyum.sh
```
Runs the full backend suite (discrimination tests + must-fail fraud fixtures + the adversarial
robustness battery), then regenerates the synthetic corpus. **269 tests**, deterministic.

## Deploy

One command brings up the whole stack — nginx (single origin) + backend + a **durable Postgres audit
ledger**:

```bash
docker compose up --build      # → http://localhost:8080
```

Deploy that on any Docker host, or split it across **Vercel** (frontend) + **Railway** (backend).
Both paths, plus how to install the real CCA-India trust anchor, are in [`DEPLOY.md`](DEPLOY.md). The
stack is built and verified: the audit chain persists across a backend restart (proven).

---

*Built for SuRaksha Cyber Hackathon 2.0 · Canara Bank. Authoritative design in
[`architecture/`](architecture/); engineering charter in [`CLAUDE.md`](CLAUDE.md).*
