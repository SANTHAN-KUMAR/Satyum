# Satyum — Synthetic Test Corpus

A drag-and-drop kit for evaluating Satyum. **Every file here is fully synthetic** (no real customer
data) and reproducible from [`generate.py`](generate.py) — nothing is a hand-tuned fixture. Each
artifact targets a specific layer of the v2 progressive-evidence pipeline
([ADR-004](../architecture/ADR-004-v2-progressive-evidence-architecture.md)) — provenance, the
deterministic financial rule pack, cross-source corroboration — and has a **documented expected
verdict** you can confirm live in the evidence console or via the API.

> Regenerate at any time: `python samples/generate.py`
> The demo CA's **private key is never written** — only the public root (`trust/demo_ca_root.pem`),
> so Tier-1 can verify the genuine signed PDF. (Regenerating mints a fresh CA + matching root.)

## How to test

**In the UI** — open the app, pick the matching tab, drag a file in:

| Tab | Use these files |
|---|---|
| **File upload** | anything in `pdfs/` or `statements/` |
| **Document bundle** | all files from `bundle_consistent/` (or `bundle_mismatch/`) together |

**To make Tier-1 cryptographic verification pass**, start the backend pointed at this kit's public
root so the signed PDF chains to a trusted anchor:

```bash
SATYUM_TRUST_ANCHOR_DIR="$(pwd)/samples/trust" uvicorn app.main:app   # from backend/, venv active
```

Without that anchor the signed PDF still verifies its *structure* but fails **closed** (untrusted
chain) — which is itself the correct, safe behaviour.

## What each file demonstrates (and its expected verdict)

### `pdfs/` — Layer 1, cryptographic signature verification (PAdES → CCA-India-style PKI)

| File | Expected verdict | What it proves |
|---|---|---|
| `genuine_signed.pdf` | ✅ **APPROVED** · source-verified | A valid PAdES signature chaining to the trusted demo root → integrity answered at the root. |
| `attacker_self_signed.pdf` | ❌ **REJECTED** · tampered | A signature exists but its chain does **not** reach a pinned anchor → *"signature exists" ≠ "signature valid"*. Fail-closed. |
| `appended_after_signature.pdf` | ❌ **REJECTED** · tampered | The PAdES **shadow attack**: bytes appended after the signed `/ByteRange` → coverage no longer spans the file. Caught. |
| `unsigned.pdf` | ⚠️ **REVIEW** · forensic-fallback | No signature → falls through to forensics; clean wrapper but content unverifiable → REVIEW, never an unearned pass. |

### `statements/` — Layer 4, the deterministic financial rule pack (arithmetic / cross-field consistency — the primary tamper signal)

| File | Expected verdict | What it proves |
|---|---|---|
| `genuine_statement.png` | ✅ **APPROVED** | Every running-balance / total invariant reconciles. |
| `tampered_statement.png` | ❌ **REJECTED** | A single balance figure was inflated (`15,000 → 16,000`); the running-balance chain breaks and the exact row is flagged. Open *"Show analysis detail"* on the arithmetic signal to see the broken invariant. |

### `hard/` — realistic, *convincing* adversarial documents

The files above prove the engine **logic** on clean toy renders. The `hard/` corpus proves the same
deterministic rule pack and Layer-1 verification on documents that **look like real bank artifacts** —
a professional multi-transaction statement (branded header, ₹ formatting, a month of UPI/salary/rent
activity) and a PAdES-signed **e-statement with visible content** — so a skeptical reviewer sees the
system survive a forgery the eye would miss, not a cake-walk. Same reproducible generator, same
numbers the suite asserts on
([`backend/tests/test_hard_fixtures.py`](../backend/tests/test_hard_fixtures.py)).

| File | Expected verdict | What it proves |
|---|---|---|
| `statement_genuine.png` | ✅ **APPROVED** (~100) | A realistic month-long statement whose running balance, totals, and net reconciliation all check out. |
| `statement_tampered.png` | ❌ **REJECTED** (~47) | The **income-inflation forgery**: one salary credit is inflated `85,000 → 185,000` while the printed balances/totals stay genuine. Looks clean; breaks the running-balance chain **and** the credit total **and** the net reconciliation. The findings panel names the exact figures (expected ₹285,000.00 vs printed ₹185,000.00). |
| `signed_statement_genuine.pdf` | ✅ **APPROVED** · source-verified (99) | The realistic statement rendered to a PDF and **PAdES-signed** by the demo root — Layer 1 verifies a document that visibly *is* a bank e-statement, not a blank page. (Needs `SATYUM_TRUST_ANCHOR_DIR`, as above.) |
| `signed_statement_shadow_attacked.pdf` | ❌ **REJECTED** · tampered (5) | The same signed e-statement with a **post-signing incremental edit** — `/ByteRange` coverage breaks, so the shadow attack is caught on a document that otherwise looks legitimately signed. |

### `bundle_consistent/` & `bundle_mismatch/` — Layer 6, cross-source corroboration / the identity graph (the ADR-003 #3 thesis, now [ADR-004 §3 Layer 6](../architecture/ADR-004-v2-progressive-evidence-architecture.md))

Submit **both files in a folder together** on the **Document bundle** tab.

| Bundle | Expected verdict | What it proves |
|---|---|---|
| `bundle_consistent/` | ⚠️ **REVIEW** (corroborated) | The statement and the ID carry the **same** identity (name + PAN) → the bundle corroborates. (REVIEW, not APPROVED — corroboration is not a substitute for verifying each document.) |
| `bundle_mismatch/` | ❌ **REJECTED** | The two documents carry **different PANs** → a hard identity mismatch floors the verdict regardless of either document's own score. |

### `trust/demo_ca_root.pem`

The **public** root of the demo CA (a stand-in for the CCA-India PKI). Point
`SATYUM_TRUST_ANCHOR_DIR` at this directory so `genuine_signed.pdf` verifies. Safe to share — it is a
public certificate, never a private key.

## Going further — the adversarial battery

These samples are the *happy-path demonstration*. The robustness evidence — single-field tampering at
scale, an OCR degradation sweep proving the system fails **closed** (never a false clear) rather than
hallucinating, and copy-move detection — lives in
[`backend/tests/test_adversarial_battery.py`](../backend/tests/test_adversarial_battery.py). Run the
whole verification in one command from the repo root:

```bash
./scripts/verify-satyum.sh
```
