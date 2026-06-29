# Satyum — Demo & Test Runbook

How to **run, test, and convincingly demonstrate every feature** of Satyum — the real-time
document-integrity evidence console for bank underwriting. Every verdict below was observed
end-to-end through the real waterfall (orchestrator → analyzers → risk engine), not asserted from
memory. Every sample is fully synthetic and reproducible (`python samples/generate.py`).

> **The one thing to internalise:** **the model reads; deterministic rules decide.** A vision-language
> model reads arbitrary document layouts into a canonical claim graph, but every number it reports is
> box-grounded and independently re-read, and a **deterministic, explainable rule engine — not the
> model — sets the verdict.** Drag a document in, and the console tells you **what changed, where, why
> it's risky, and what to do** — and you can prove the judgment isn't faking by editing one figure and
> watching the verdict move (see §5). (Full architecture:
> [ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md).)

---

## 1. Start the stack

### Option A — one command (recommended for a demo)
```bash
docker compose up --build
# → open http://localhost:8080
```
Nginx serves the app and proxies `/api` + `/ws` to the backend; Postgres gives a durable, hash-chained
audit ledger; the demo CA root is bundled in the image so source-of-truth crypto verifies the signed
samples. `localhost` is a secure origin, so the **camera works** without HTTPS.

### Option B — local dev (two terminals)
```bash
# Terminal 1 — backend (source-of-truth verification pinned to the demo CA root so signed PDFs verify)
cd backend && source .venv/bin/activate
SATYUM_TRUST_ANCHOR_DIR="$(pwd)/../samples/trust" uvicorn app.main:app   # :8000

# Terminal 2 — frontend (Vite proxies /api and /ws to :8000)
cd frontend && npm install && npm run dev                                # → http://localhost:5173
```

**Health check (and proof the audit chain is intact):**
```bash
curl -s localhost:8080/api/health   # docker   (or :8000 for local dev)
# {"status":"ok","analyzers":16,"audit_backend":"postgres","audit_chain_intact":true,...}
```

> **Source-of-truth trust anchor:** the demo-signed PDFs verify only when the backend pins this kit's
> public root ([`samples/trust/demo_ca_root.pem`](samples/trust/demo_ca_root.pem)). Docker bundles it.
> Locally, set `SATYUM_TRUST_ANCHOR_DIR` as shown. **Without it the signed PDFs fail _closed_**
> (untrusted chain) — which is itself correct, safe behaviour, just not the "green" you want on stage.

---

## 2. The 5-minute headline demo (tell the story)

Run these four in order — it walks the **progressive-evidence pipeline**: provenance first, then the
model *reads* and deterministic rules *decide*, then in-person capture. Use the **File upload** tab
unless noted.

| # | Drag in | You'll see | The line to say |
|---|---|---|---|
| 1 | `samples/hard/signed_statement_genuine.pdf` | ✅ **APPROVED · source-verified** | "A bank e-statement with a real digital signature. We verify the signature chains to the CCA-India root **before trusting a single byte** — integrity answered at the source. Verified means byte-authenticity, so the claims still flow into corroboration." |
| 2 | `samples/hard/signed_statement_shadow_attacked.pdf` | ❌ **REJECTED · tampered** | "Same signed statement, but someone edited it *after* signing. 'A signature exists' is not 'a signature is valid' — we catch that the signature no longer covers the whole file. The shadow attack." |
| 3 | `samples/hard/statement_tampered.png` | ❌ **REJECTED** — arithmetic finding names the figures | "No signature to lean on — a scanned statement. **The model reads the layout into typed claims; deterministic rules judge them.** A forger inflated their salary credit, but they **can't keep the document's math coherent** — the financial rule pack recomputes every running balance (expected ₹285,000 vs printed ₹185,000), and every number is independently re-read so the model can't quietly 'correct' a tamper into consistency." |
| 4 | **Live capture** tab → perform the challenge (see §4) | ⚠️/✅ live verdict with the active-challenge result | "For wet-ink or contested *physical* paper, the server issues an **unpredictable physical challenge** and verifies the document's tracked motion — defeating a photo-of-a-screen or a pre-recorded clip." |

Then point at the console itself: the **trust gauge**, the **provenance card**, the **per-signal
findings** with their mode tags, and the **Not-evaluated (pending)** list — *"nothing that didn't run
is shown as a pass."*

---

## 3. Every feature — what to drag, expected verdict, what it proves

### Source of truth — cryptographic provenance (File upload)
| Sample | Verdict (score) | Proves |
|---|---|---|
| `hard/signed_statement_genuine.pdf` | ✅ APPROVED (99) · source-verified | Full PAdES chain validation to a **pinned** anchor, on a document with visible content. |
| `pdfs/genuine_signed.pdf` | ✅ APPROVED (99) · source-verified | Same, minimal PDF. |
| `pdfs/attacker_self_signed.pdf` | ❌ REJECTED (5) · tampered | Attacker's own cert → chain doesn't reach the anchor → fail-closed. |
| `pdfs/appended_after_signature.pdf` | ❌ REJECTED (5) · tampered | Bytes appended after the signed `/ByteRange` (shadow / incremental-update attack). |
| `hard/signed_statement_shadow_attacked.pdf` | ❌ REJECTED (5) · tampered | The shadow attack on a **realistic** signed e-statement. |
| `pdfs/unsigned.pdf` | ⚠️ REVIEW · forensic-fallback | No signature → falls through to forensics; never an unearned pass. |

### Judgment — financial rule pack over the claim graph (File upload) — the primary tamper signal
The model reads each statement into typed claims; the deterministic **financial rule pack** (rehomed
from the v1 arithmetic engine) judges them, and every numeric claim is independently re-read before a
rule trusts it.
| Sample | Verdict (score) | Proves |
|---|---|---|
| `hard/statement_genuine.png` | ✅ APPROVED (~100) | A realistic month of activity that reconciles to the cent. |
| `hard/statement_tampered.png` | ❌ REJECTED (~47) | One inflated salary credit breaks **three** invariants: running balance, credit total, net reconciliation. Open the arithmetic finding to see the exact figures. |
| `statements/genuine_statement.png` | ✅ APPROVED | Clean toy statement (the minimal logic demo). |
| `statements/tampered_statement.png` | ❌ REJECTED | A single inflated balance figure; the chain breaks at the exact row. |

### Corroboration — cross-document identity graph (Document bundle tab — submit **all files in the folder together**)
| Bundle | Verdict | Proves |
|---|---|---|
| `bundle_consistent/` (both PNGs) | ⚠️ REVIEW (corroborated) | Statement + ID carry the **same** name + PAN → the bundle corroborates one identity. |
| `bundle_mismatch/` (both PNGs) | ❌ REJECTED | The two documents carry **different PANs** → a hard identity mismatch floors the verdict regardless of either document's own score. The graph names both documents and both values. |

### In-person escalation — live capture, the active 3D challenge (Live capture tab) — see §4.

---

## 4. The live-camera demo (in-person escalation)

The camera path is the **in-person escalation for wet-ink / contested *physical* documents** (not the
financial-statement primary path). It is wired end-to-end: the browser streams downscaled frames over a
WebSocket, the server issues a **server-randomized** tilt challenge, and `ActiveChallengeAnalyzer`
verifies the realised motion against the command via homography. **Frames are processed in memory and
never persisted.**

**To run it:**
1. Open the **Live capture** tab → **Start live session** → grant camera permission.
2. Hold a **printed, text-bearing document** in frame (a printout of `hard/statement_genuine.png`
   works well — the tracker needs texture; a blank sheet won't track).
3. Read the on-screen instruction, e.g. *"Tilt the document's left edge toward the camera about 20°,
   and hold steady."* Perform that tilt **deliberately and hold** while the countdown runs.
4. After ~5 seconds the server auto-scores and the verdict appears, with the `active_challenge`
   finding ("commanded y-tilt 20° realised 20.6° on a single consistent homography — live document").

**What proves it's real:**
- **Hold still / don't tilt** → "challenge unmet" (high suspicion). The verdict moves with your motion.
- **Point the camera at a photo of a document on another screen** → the bezel/double-perspective
  breaks the single-homography consistency check → flagged as photo-of-screen.
- The challenge axis + magnitude are **randomized per session** — a pre-recorded clip can't satisfy a
  command issued only after the session starts.

> Honest bound (stated in the UI and the code): this defeats *presentation* replay (a clip, a
> photo-of-screen), **not** stream *injection* (a virtual camera) — which needs native platform
> attestation and is a separate, low-weight, documented-bypassable check.

---

## 5. How to prove it's NOT faking (for the skeptical evaluator)

This is the most important part — a fraud system whose own code lies is self-defeating, so Satyum is
built to be *checkable*. The decision is **deterministic**: the rules recompute the document's logic,
and the verdict moves with the input. (The *reading* layer is separately guarded — every numeric claim
the VLM locates is independently re-read by a deterministic OCR on its exact crop, so the model can't
quietly "auto-correct" a tampered cell into consistency; disagreement → `NOT_EVALUATED`, never a silent
pick. See [ADR-004](architecture/ADR-004-v2-progressive-evidence-architecture.md) §5.2.)

**Live, in front of them:**
- Open `samples/hard/statement_genuine.png` in any image editor, change one balance digit, save, and
  drag it in. The verdict flips to REJECTED and the finding names the **new** broken figure. The
  output moves with the input — it's recomputing, not pattern-matching.
- Drag the genuine and tampered versions back to back: APPROVED ↔ REJECTED from a one-figure change.

**In the test suite (every detector ships a genuine-vs-adversarial pair + must-fail fixtures):**
```bash
cd backend && source .venv/bin/activate
python -m pytest -q                         # 282 tests, all green
python -m pytest tests/test_hard_fixtures.py -v      # the realistic corpus, asserted end-to-end
python -m pytest tests/test_constant_return_guard.py -v   # proves a constant-return analyzer FAILS
python -m pytest tests/test_camera_ws.py -v          # the live-capture wire path, end-to-end
python -m pytest tests/test_signature.py -v          # self-signed + appended-bytes MUST fail
```
The litmus the suite enforces (CLAUDE.md §3.2): *if you replaced any analyzer with `return <constant>`,
its test would fail* — because a constant can't pass the genuine artifact **and** flag the forged one.

**Regenerate the whole corpus from scratch** (nothing is a hand-tuned binary):
```bash
python samples/generate.py
```

---

## 6. The cybersecurity spine (talking points)

- **Applied PKI, done right.** Full chain-to-pinned-anchor validation, `/ByteRange` coverage, and
  shadow-attack detection — not "a signature is present."
- **Fail-closed everywhere.** Any error, timeout, or indeterminate aggregate degrades to **REVIEW**,
  never auto-APPROVE. A crashing analyzer never crashes the verdict. (Try it: the camera with no
  motion, or an unparsable upload, both land safe.)
- **Tamper-evident audit.** Every verdict is appended to a **hash-chained** ledger; `/api/health`
  reports `audit_chain_intact`. Editing any past record breaks the chain at that row.
- **Privacy by design.** Camera frames live in memory for the session only and are never persisted;
  no document bytes or PII are logged; the audit stores decision metadata, not imagery.
- **The model reads; deterministic rules decide.** **No ML/VLM sits in the decision path** — the VLM
  is an untrusted, box-grounded, cross-read-verified *input* with zero decision authority; cryptography
  + `Decimal` rules + logic set the verdict. Determinism holds **from the claim graph onward**, so the
  same claim graph + config always yields the same, fully-traceable verdict; the cloud-POC VLM read is
  bounded by the numeric cross-read, and the self-hosted production path (Qwen2.5-VL pinned
  in-perimeter) restores full extraction reproducibility too.

---

## 7. Quick reference — sample → verdict

| Sample | Tab | Verdict |
|---|---|---|
| `hard/signed_statement_genuine.pdf` | File upload | ✅ APPROVED · source-verified |
| `hard/signed_statement_shadow_attacked.pdf` | File upload | ❌ REJECTED · tampered |
| `hard/statement_genuine.png` | File upload | ✅ APPROVED |
| `hard/statement_tampered.png` | File upload | ❌ REJECTED · arithmetic |
| `pdfs/genuine_signed.pdf` | File upload | ✅ APPROVED · source-verified |
| `pdfs/attacker_self_signed.pdf` | File upload | ❌ REJECTED · tampered |
| `pdfs/appended_after_signature.pdf` | File upload | ❌ REJECTED · tampered |
| `pdfs/unsigned.pdf` | File upload | ⚠️ REVIEW |
| `statements/genuine_statement.png` | File upload | ✅ APPROVED |
| `statements/tampered_statement.png` | File upload | ❌ REJECTED |
| `bundle_consistent/` (both) | Document bundle | ⚠️ REVIEW · corroborated |
| `bundle_mismatch/` (both) | Document bundle | ❌ REJECTED · identity mismatch |
| live document + tilt | Live capture | live verdict (challenge result) |

*Verdicts observed end-to-end on 2026-06-28. Trust anchor = `samples/trust/`. Scores are deterministic
given the same config.*
