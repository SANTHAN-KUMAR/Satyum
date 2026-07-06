# Satyum (सत्यम्, "truth")

A real-time document-integrity evidence console for bank underwriting.

Built for SuRaksha Cyber Hackathon 2.0, Canara Bank, Theme 1 (real-time anomaly detection in
financial documents). Written and tested as if it were going into production for a regulated lender.

Satyum tells an underwriter what changed in a document, where, why it matters, and what to do about
it, before that document is allowed to inform a lending decision. It produces an explainable trust
score (0-100) and an Underwriter Evidence Pack. Underneath, it's a security system as much as a
document-analysis one: certificate chain verification, anti-spoofing capture checks, a fail-closed
pipeline, and a tamper-evident audit trail, all wrapped around the document-fraud problem.

## The core idea

The model reads. Deterministic rules decide.

A forger can fake a document's pixels, but they can't easily keep its underlying arithmetic and
logic coherent. Provenance checks and open banking already solve the easy case, a document you can
pull straight from its source. The harder case, and the one most fraud slips through today, is the
document you can't source: a scanned bank statement, a co-op or regional bank's own format, a
wet-ink deed, a vernacular-language document.

Satyum's answer: use a vision-language model to read whatever layout is in front of it into a
canonical set of claims (amounts, dates, names, running balances), then hand that claim graph to
deterministic rules that recompute the document's own arithmetic. The model only reads. It never
gets to decide whether something is fraudulent, and every number it extracts is independently
re-read by a separate OCR pass before any rule is allowed to trust it. See
[ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md) for the full design and why
the VLM is treated as untrusted input.

The signals, roughly in order of how much weight they carry:

1. **Arithmetic and cross-field consistency** (the primary signal). Every invariant in the claim
   graph gets recomputed: running balance, totals, net reconciliation, salary vs. take-home. A
   single edited figure breaks the math and gets localized to the exact cell. This is pure `Decimal`
   logic, no machine learning involved in the judgment itself.
2. **Cross-document corroboration.** The same identity (PAN, Aadhaar number, name, date of birth)
   has to agree across the statement, the ID, and the salary slip or Form 16. A hard mismatch is
   close to disqualifying on its own.
3. **Resubmission memory.** A perceptual hash catches the same forged document being reused across
   different applicants.
4. **Active 3D challenge.** For wet-ink or otherwise contested physical documents, an in-person
   escalation step asks the applicant to tilt the physical document by a server-chosen amount and
   verifies the motion by homography. A flat photo or screen replay can't satisfy it.

## The pipeline

A progressive-evidence waterfall: verify what can be cryptographically verified, read what can't be
verified another way, judge with deterministic rules, corroborate across the whole document bundle,
and fail closed whenever the evidence isn't sufficient. Every signal is tagged with the mode it ran
in, so a signal that only makes sense for a file can never show up as "passed" on a camera frame.

| Layer | How it works |
|---|---|
| 1. Source of truth | PAdES/CMS signature verification chaining to a pinned PKI root (pyHanko), plus C2PA content provenance. Catches attacker certificates and appended-byte tampering after signing. A verified signature proves the bytes are authentic, not that the claims inside are true, so verified documents still go through the rest of the pipeline. |
| 2-3. Understanding | A vision-language model reads the document into typed fields and tables, each tagged with page, bounding box, and confidence. Every numeric claim is independently re-read by OCR and has to agree, or it's marked not evaluated rather than guessed at. The model has zero decision authority. |
| 4. Judgment | Rule packs run over the claim graph. The financial pack (running balance, totals, salary reconciliation) is built out in full depth; land and legal rule packs exist but are honestly scoped, anything they don't cover returns not evaluated instead of a fake pass. |
| 5. Anomaly (soft) | A deterministic statistical layer plus an optional, off-by-default machine learning lane. This can only push a case to review, never approve or reject on its own. |
| 6. Corroboration | Cross-document identity and income checks. A single document with nothing to corroborate against resolves to review, not a pass. |
| 7. Decision | A guarded policy engine outputs approve, review, reject, or pending. A few invariants are hard-coded here: the model alone can never approve a case, clean arithmetic alone doesn't mean genuine, and missing evidence never turns into a pass. |
| Interpretability | A narrator turns the finished evidence pack into a short plain-English summary, and an underwriter copilot answers follow-up questions using read-only tools over that frozen evidence. A firewall discards any explanation that contradicts the real verdict, so even a compromised or hallucinating explainer can't move the decision. |
| In-person escalation | Live camera capture for contested physical documents: image rectification, quality checks, the active tilt challenge, and anti-spoof checks. This defends against someone holding up a photo or a screen, not against a virtual camera feed, which needs OS-level attestation and isn't something a browser can fully solve. |

### What Satyum deliberately doesn't do

A few well-known techniques are left out on purpose, not because they were too hard, but because
they don't hold up: error-level analysis, PRNU, LSB or DCT steganalysis, and neural GAN or GradCAM
heatmaps all collapse against modern GenAI forgeries and are treated as unreliable in this project.
rPPG, micro-expression analysis, and deepfake detection belong to a separate, consent-gated identity
verification mode and never feed into the document trust score. And the model that reads a document
never gets a vote in judging it. Everything from the claim graph onward is deterministic: given the
same claim graph and the same configuration, the verdict is reproducible and every contributing
signal is traceable.

### Handling messy real-world documents

Real government and bank documents don't arrive in clean shape, and the pipeline is built to handle
that honestly instead of failing on legitimate submissions. Aadhaar PDFs, CAMS or Karvy statements,
and signed e-statements often ship password-protected: Satyum detects that and asks for the password
inline rather than treating it as an error, then decrypts in memory at every point it's needed
without ever re-saving the file, which matters because re-saving would destroy the original digital
signature. Separately, when the deterministic OCR fallback misreads a balance cell on a dense
multi-page statement, a plausibility check drops the obviously wrong figure instead of letting it
cascade into a false rejection, while a genuinely tampered figure still gets flagged. See
[ADR-006](architecture/ADR-006-interpretability-and-resilience.md) for both.

## Repository layout

```
Satyum/
├── architecture/        design docs; start with ADR-004 for the current architecture
├── backend/              FastAPI service
│   ├── app/              routes, orchestrator, contracts, claim graph
│   ├── verification/     signature and provenance checks (Tier 1)
│   ├── forensics/        rule packs, OCR cross-read, metadata, copy-move, perceptual hash
│   ├── interpretability/ narrator and underwriter copilot, firewalled off the verdict
│   ├── federation/       cross-institution fraud-ring detection (see ADR-005)
│   ├── providers/        Aadhaar, PAN, DigiLocker, Account Aggregator integrations
│   ├── capture/          live camera escalation (active challenge, anti-spoof, rectify)
│   └── risk/             scoring, evidence pack, hash-chained audit log
├── frontend/             React + TypeScript + Vite + Tailwind evidence console
├── samples/              full synthetic and generated test corpus, used by the test suite
├── demo/                 a smaller, curated set of documents for live demos (see demo/README.md)
├── scripts/              corpus and demo-bundle generators, trust anchor installer
└── DEPLOY.md             deployment guide (Docker, or Vercel + Railway)
```

## Running it locally

**Backend** (Python 3.11+, needs `tesseract-ocr` installed on the system):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
SATYUM_TRUST_ANCHOR_DIR="../samples/trust" uvicorn app.main:app --reload
```

The document-understanding layer needs a VLM to read documents. Set an API key for the reader you
want to use, for example `ANTHROPIC_API_KEY` for Claude. In production this swaps to a self-hosted
Qwen2.5-VL endpoint behind the same interface, a config change rather than a rewrite. The extraction
interface also supports Gemini, Groq, and any OpenAI-compatible endpoint (Cloudflare Workers AI,
OpenRouter, Together, local Ollama). See [DEPLOY.md](DEPLOY.md) for the full environment variable
list, including how to point the narrator and copilot at a separate text model from the document
reader.

**Frontend** (Node 18+):
```bash
cd frontend
npm install && npm run dev
```
This proxies `/api` and `/ws` to the backend automatically.

**Try it out.** Open the app and drag in files from [`demo/`](demo/README.md), the demo folder walks
through signature verification, statement tampering, and identity mismatches with the exact verdict
each file should produce.

## Running the test suite

```bash
./scripts/verify-satyum.sh
```
Runs the full backend test suite, including the must-fail fraud fixtures and the adversarial
robustness battery, then regenerates the synthetic corpus so nothing in it is hand-edited.

## Testing and evaluation

See [RESULTS.md](RESULTS.md) for the test suite breakdown, the evaluation methodology (what metrics
matter for a fraud-detection system and why), and an honest accounting of what's measured versus
what still needs a real run.

## Deploying

```bash
docker compose up --build
```
brings up nginx, the backend, and a Postgres-backed audit ledger in one command, reachable at
`http://localhost:8080`. The same stack can be deployed to any Docker host, or split across Vercel
(frontend) and Railway (backend). Both paths, along with how to install a real production trust
anchor, are covered in [DEPLOY.md](DEPLOY.md).

---

Built for SuRaksha Cyber Hackathon 2.0, Canara Bank. Design documents live in
[`architecture/`](architecture/); engineering guidelines are in [`CLAUDE.md`](CLAUDE.md).
