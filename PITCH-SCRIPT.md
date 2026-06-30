# Satyum — Pitch Demo Script (≈4 min)

The recordable walkthrough for the judged demo. Built to **lead with what is judge-proof** (deterministic,
verified) and only *then* show the VLM-read fallback — so a skeptical judge never sees us lean on a
stochastic model for a verdict. Every number below was **observed end-to-end on this machine**, not
asserted from memory (CLAUDE.md §3.5). The two facts marked **[live]** are run at record-time.

> **The one line to open and close with:** *"A forger can fake the pixels, but they can't keep the
> document's logic coherent. So we let a model **read** the document — but only deterministic rules,
> cryptography, and arithmetic **decide**. Even a fully prompt-injected reader cannot move our verdict."*

---

## 0. Pre-flight (have these ready before recording)

```bash
# Backend pinned to the demo CA root so the signed PDFs verify (else they correctly fail closed).
cd backend && source .venv/bin/activate
SATYUM_TRUST_ANCHOR_DIR="$(pwd)/../samples/trust" uvicorn app.main:app          # :8000

# Frontend
cd frontend && npm run dev                                                       # :5173
```
- For the **arithmetic act**, set the reader to **Gemini** (handles the 5-page real statement; free-tier
  Cloudflare/Mistral times out on dense multi-page — that's a throughput limit, not a logic limit):
  `SATYUM_VLM_PROVIDER=gemini  SATYUM_VLM_MODEL=gemini-2.5-flash  SATYUM_VLM_API_KEY=…`
- Health + audit proof to show once: `curl -s localhost:8000/api/health` → `audit_chain_intact: true`.

---

## Act 1 — Source of truth (the security spine). **No model. Pure PKI.** ✅ *verified*

> Upload tab. This is the strongest evidence and it is **100% deterministic** — open here.

| Drag in | Verdict (observed) | The line to say |
|---|---|---|
| `samples/pdfs/genuine_signed.pdf` | ✅ **APPROVED · 99** — `pades_signature: verified, chains to a pinned trust anchor` | "Before we trust a single byte, we verify the PDF's cryptographic signature chains to the CCA-India root. This is what DigiLocker and signed bank e-statements carry." |
| `samples/pdfs/attacker_self_signed.pdf` | ❌ **REJECTED · 5** — `signature INVALID — chain doesn't reach the anchor` | "Attacker signs with their *own* certificate. 'A signature exists' is not 'a signature is valid' — the chain doesn't reach our pinned root, so we fail **closed**." |
| `samples/pdfs/appended_after_signature.pdf` | ❌ **REJECTED · 5** — `signature INVALID` **and** `pdf_structure: incremental update appended after the signature` | "The shadow attack — bytes edited *after* signing. **Two** independent signals catch it: the digest no longer covers the file, and the structure shows a post-signature update." |

**Say:** *"Notice nothing that didn't run shows green — the signature line on an unsigned doc reads
**not-evaluated**, never a pass."* (Optional: `samples/pdfs/unsigned.pdf` → ⚠️ **REVIEW · 60**, falls to forensics.)

---

## Act 2 — The model reads, the rules decide (the crown jewel). ✅ *engine verified* / **[live]** *read*

> Upload tab, **a real-layout Canara statement** (not a toy) — `samples/real_corpus/canara_direct/`.

1. **Genuine** → `genuine.pdf` → **APPROVED**. *"A real bank statement. The model reads the layout into
   typed claims; the deterministic financial rule pack recomputes every running balance and total."*
2. **Tampered** → `tamper_closing_balance.pdf` (the *same* statement, **one figure changed**) →
   ❌ **REJECTED**, and the arithmetic finding **names the exact cell** — expected vs printed. *"They
   edited one number. They can't keep the math coherent — the running balance no longer reconciles, and
   because every figure is independently re-read, the model can't quietly 'correct' the tamper into
   consistency."*

**The "prove it isn't faking" beat (strongest 15 seconds of the demo):** *"This isn't a model guessing —
it's arithmetic. Our discrimination tests show genuine passes, a single-field edit fails, and if we
replaced the analyzer with `return APPROVED` the test suite breaks. The decision path has no model in
it."* — backed by `tests/test_arithmetic.py` + `tests/test_constant_return_guard.py` (**29 pass, 0.98s**).

> **[live] note:** run the genuine vs tampered pair once during rehearsal on the Gemini key so the
> on-screen verdicts are real. The *engine's* discrimination is already proven deterministically; the
> live run just shows the read working end-to-end on a real 5-page document.

---

## Act 3 — Corroboration across the bundle. **[live]** *read*

> **Document bundle** tab — submit a whole folder together.

- `demo_bundles/04_Corpus_Identity_Mismatch/` → ❌ **REJECTED** — the documents carry **different
  identities**; the cross-document graph names both docs and both values and floors the verdict
  regardless of each doc's own score. *"This is the case where the statement we pulled doesn't belong to
  the applicant on the ID — a hard mismatch, exactly the kind a busy underwriter misses."*
- Contrast with `demo_bundles/02_Corpus_Clean_Match/` → consistent identity across all four docs.

---

## Act 4 — Network intelligence (the two dashboard features). **No docs — use the simulators.**

> These show fraud that **no single bank can see alone** — the differentiator vs every per-document tool.

- **Consortium / fraud-ring memory:** submit a few applications that **reuse the same forged document or
  entity** across different banks → **Detect rings** lights up the union-find ring. *"A forged salary
  slip reused across three co-op banks — invisible to each, obvious to the consortium. We share only
  HMAC'd tokens, never raw PII."*
- **Master model / promoted rules:** **Run a mining round** → a pattern crosses the coverage threshold →
  **approve** it → **Run against the model** and watch it fire as an **advisory** (it can only push
  APPROVED → REVIEW, never change the score — the deterministic verdict stays sovereign).

---

## Close (the read-vs-decide security argument)

*"Provenance solves the sourceable document. The unsolved frontier is the **un-sourceable** one — scanned
paper, regional banks, GenAI forgeries that beat pixel forensics. Our answer: let the model read anything,
but keep cryptography and arithmetic as the only things that decide. That split is itself the security
property — a fully injected reader still can't move the verdict. Built fail-closed, mode-tagged, and
written to a tamper-evident, hash-chained audit ledger a bank auditor can replay."*

---

## Honest footnotes (say if a judge asks — these win trust)

- **Deterministically verified on this machine:** Tier-1 crypto discrimination (APPROVED 99 / REJECTED 5 /
  REJECTED 5 / REVIEW 60, audit chain intact); the arithmetic + financial rule decision path
  (29 discrimination tests + the constant-return guard).
- **VLM-read, not VLM-judged:** the model only transcribes; every numeric claim is box-grounded and
  independently re-read (Tesseract cross-read), and it can never set a verdict.
- **Honest gates (labelled, not faked):** live Income-Tax PAN existence check and Account-Aggregator pull
  need an RBI/regulator credential → shown as **pending**, never a fabricated pass. The signature, the
  arithmetic, the C2PA/PAdES verification, the ring detection — all real and running.
- **Throughput, not credibility:** dense 5-page statements need a higher-throughput reader (Gemini/Claude/
  Qwen-72B); free-tier Cloudflare is fine for ≤3-page docs. The *logic* is identical across readers.
