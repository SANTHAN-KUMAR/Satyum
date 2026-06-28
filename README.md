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

> **A forger can fake a document's pixels, but cannot keep its *logic* coherent.**

Provenance and open-banking already solve the *sourceable* document. The unsolved frontier — where
GenAI forgeries now win and pixel-forensics collapse — is the **un-sourceable** document (scanned
paper, co-op/regional statements, thin-file borrowers, wet-ink deeds). Satyum attacks the
**consistency layer, not the pixels**:

1. **Arithmetic / cross-field consistency** *(primary signal)* — recompute every invariant (running
   balance, totals, net reconciliation); a single edited figure breaks the maths and is localised to
   the exact cell. Pure logic, zero black-box ML.
2. **Active 3D challenge** — a server-randomised physical tilt, verified by homography (a flat
   screen-replay can't satisfy it).
3. **Cross-document consistency graph** — the same identity (PAN/Aadhaar/name/DOB…) must agree across
   the statement ↔ ID ↔ deed bundle; a mismatch is near-dispositive.
4. **Resubmission / fraud-ring memory** — perceptual hashing catches the same forged doc reused.

## The verification waterfall (provenance first → forensics → in-person)

Every signal is **mode-tagged** and runs only where its evidence physically exists (a file-forensic
signal can never show "passed" on a camera frame).

| Tier | When | What runs |
|---|---|---|
| **1 · Source-of-truth** | always, on files | **PAdES/CMS signature** verification chaining to a pinned PKI root (pyHanko), + **C2PA** content-provenance (trust-list pinned). Pass → integrity answered at the root; fail → **fail-closed**. |
| **2 · Forensic fallback** | no verifiable source | **OCR + arithmetic consistency (primary)**, PDF structure/metadata + shadow-attack detection, copy-move (ORB+RANSAC), font/layout anomaly, perceptual-hash resubmission, cross-document identity graph. |
| **3 · Live capture** | wet-ink / contested | WebRTC capture: rectify + quality gate, the **active 3D challenge**, anti-spoof votes (moiré/specular/temporal). Stops *presentation* attacks. |

### What we deliberately DON'T do (and why)

Honesty is a feature here. Industry-**distrusted**, near-chance, or unvalidated techniques are
**excluded or `NOT_EVALUATED`**, never faked into a green pass: **ELA, PRNU, LSB/DCT steganalysis,
neural GANs/GradCAM heatmaps** (collapse on GenAI forgeries), and **rPPG / micro-expression / deepfake**
(belong only to a separate, consented face-KYC mode — they **never feed the document score**). The
decision path is **deterministic — classical CV + cryptography + logic, no black-box ML** — so every
verdict is reproducible and explainable down to the contributing signals.

---

## Repository layout

```
Satyum/
├── architecture/            ← the authoritative design (read these)
│   ├── ADR-001 … ADR-003    ← dual-mode · provenance-first · innovation thesis
│   ├── RESEARCH-001         ← industry landscape grounding
│   ├── BUILD-MANIFEST.md    ← what's real / gated, with must-fail fixtures
│   └── TESTING-STRATEGY.md  ← the adversarial test regime
├── backend/                 ← FastAPI; deterministic verification core (269 tests)
│   ├── app/                 ← routes + orchestrator + mode-keyed registry + contracts
│   ├── verification/        ← Tier-1 crypto/provenance (PAdES, C2PA)
│   ├── forensics/           ← Tier-2 (arithmetic, OCR, metadata, copy-move, pHash, cross-doc, entities)
│   ├── capture/             ← Tier-3 camera (active challenge, anti-spoof, rectify)
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
# Point Tier-1 at the demo trust anchor so the sample signed PDF verifies:
SATYUM_TRUST_ANCHOR_DIR="../samples/trust" uvicorn app.main:app --reload
```

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
