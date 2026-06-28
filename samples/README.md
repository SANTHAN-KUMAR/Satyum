# Satyum — Synthetic Test Corpus

A drag-and-drop kit for evaluating Satyum. **Every file here is fully synthetic** (no real customer
data) and reproducible from [`generate.py`](generate.py) — nothing is a hand-tuned fixture. Each
artifact targets a specific detector and has a **documented expected verdict** you can confirm live in
the evidence console or via the API.

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

### `pdfs/` — Tier-1, cryptographic signature verification (PAdES → CCA-India-style PKI)

| File | Expected verdict | What it proves |
|---|---|---|
| `genuine_signed.pdf` | ✅ **APPROVED** · source-verified | A valid PAdES signature chaining to the trusted demo root → integrity answered at the root. |
| `attacker_self_signed.pdf` | ❌ **REJECTED** · tampered | A signature exists but its chain does **not** reach a pinned anchor → *"signature exists" ≠ "signature valid"*. Fail-closed. |
| `appended_after_signature.pdf` | ❌ **REJECTED** · tampered | The PAdES **shadow attack**: bytes appended after the signed `/ByteRange` → coverage no longer spans the file. Caught. |
| `unsigned.pdf` | ⚠️ **REVIEW** · forensic-fallback | No signature → falls through to forensics; clean wrapper but content unverifiable → REVIEW, never an unearned pass. |

### `statements/` — Tier-2, arithmetic / cross-field consistency (the primary tamper signal)

| File | Expected verdict | What it proves |
|---|---|---|
| `genuine_statement.png` | ✅ **APPROVED** | Every running-balance / total invariant reconciles. |
| `tampered_statement.png` | ❌ **REJECTED** | A single balance figure was inflated (`15,000 → 16,000`); the running-balance chain breaks and the exact row is flagged. Open *"Show analysis detail"* on the arithmetic signal to see the broken invariant. |

### `bundle_consistent/` & `bundle_mismatch/` — the cross-document identity graph (ADR-003 #3)

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
