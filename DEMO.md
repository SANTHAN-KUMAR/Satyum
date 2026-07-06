# Demo runbook

How to run and demonstrate Satyum end to end. Every verdict quoted below was actually observed
running the real pipeline (orchestrator, analyzers, risk engine), not written from memory. The demo
documents in [`demo/`](demo/README.md) are fully synthetic or generated from public sample templates
and are checked into the repo, so they're there right after a fresh clone.

The one thing worth saying out loud during a demo: the model reads, deterministic rules decide. A
vision-language model reads a document's layout into typed claims, every number it reports is
independently re-read by a separate OCR pass, and a deterministic, explainable rule engine sets the
verdict, not the model. Drag a document in and the console shows what changed, where, and why. You
can prove the judgment isn't faked by editing one figure in a genuine document and watching the
verdict move (see the "proving it's real" section below).

## 1. Start the stack

**Option A, one command:**
```bash
docker compose up --build
# open http://localhost:8080
```
Nginx serves the app and proxies `/api` and `/ws` to the backend. Postgres backs a durable,
hash-chained audit ledger. The demo certificate authority root is baked into the image so the signed
sample PDFs verify out of the box. `localhost` counts as a secure origin, so the camera works without
needing HTTPS.

**Option B, two terminals for local dev:**
```bash
# backend, pinned to the demo trust anchor so the signed sample PDFs verify
cd backend && source .venv/bin/activate
SATYUM_TRUST_ANCHOR_DIR="$(pwd)/../samples/trust" uvicorn app.main:app   # :8000

# frontend, proxies /api and /ws to :8000
cd frontend && npm install && npm run dev                                # http://localhost:5173
```

Health check, also confirms the audit chain is intact:
```bash
curl -s localhost:8080/api/health
# {"status":"ok","analyzers":16,"audit_backend":"postgres","audit_chain_intact":true,...}
```

Without `SATYUM_TRUST_ANCHOR_DIR` pointing at `samples/trust`, the signed demo PDFs fail closed
(untrusted chain), which is correct behavior, just not what you want mid-demo.

## 2. A five-minute walkthrough

Run these in order, using the File upload tab unless noted. This walks through the pipeline in the
order it actually runs: provenance first, then reading and judging, then in-person capture.

| # | Drag in | You'll see | What to say |
|---|---|---|---|
| 1 | `demo/01_signature_verification/genuine_signed.pdf` | APPROVED, source-verified | "This PDF carries a real digital signature. We check that it chains to a trusted root before trusting a single byte of content." |
| 2 | `demo/01_signature_verification/appended_after_signature.pdf` | REJECTED, tampered | "Same idea, but someone appended bytes to this file after it was signed. A signature existing isn't the same as a signature being valid over the whole file, and we catch the difference." |
| 3 | `demo/02_statement_tampering/tampered_salary_inflate.pdf` | REJECTED, arithmetic finding names the row | "No signature to lean on here, a plain scanned-style statement. The model reads the layout into structured claims, then deterministic rules recompute the running balance. Someone inflated a salary credit, and the math simply doesn't add up anymore. The finding names the exact figure." |
| 4 | Live capture tab, perform the tilt challenge (see section 4) | Live verdict with the challenge result | "For wet-ink or contested physical paper, the server asks for an unpredictable tilt and checks the real motion, which defeats a photo of a screen or a pre-recorded clip." |

Then point at the console itself: the trust score, the provenance card, the individual findings with
their status, and the "not evaluated" list, nothing that didn't actually run is shown as a pass.

## 3. Every feature, what to drag in, and what it proves

### Signature verification (File upload tab)

| File | Verdict | Proves |
|---|---|---|
| `demo/01_signature_verification/genuine_signed.pdf` | APPROVED, source-verified | Full chain validation to a pinned trust anchor. |
| `demo/01_signature_verification/attacker_self_signed.pdf` | REVIEW, issuer unconfirmed | The signature is intact but signed by an untrusted certificate. This is deliberately not labeled "tampered": the bytes are unaltered, and a genuine document from an issuer we simply haven't pinned yet would look identical. We don't accuse a document of fraud just because its issuer isn't in our trust list. |
| `demo/01_signature_verification/appended_after_signature.pdf` | REJECTED, tampered | Bytes were appended after the signed byte range. The content actually changed, so this is real tampering. |
| `demo/01_signature_verification/unsigned.pdf` | REVIEW | No signature, falls through to document-level analysis, never an unearned pass. |

### Financial rule pack over the claim graph (File upload tab), the primary tamper signal

The model reads each statement into typed claims. The financial rule pack judges them, and every
numeric claim is independently re-read before any rule is allowed to trust it.

| File | Verdict | Proves |
|---|---|---|
| `demo/02_statement_tampering/genuine_statement.pdf` | APPROVED or REVIEW | A statement whose numbers reconcile end to end. |
| `demo/02_statement_tampering/tampered_closing_balance.pdf` | REJECTED | Closing balance doesn't match the running total. |
| `demo/02_statement_tampering/tampered_salary_inflate.pdf` | REJECTED | One inflated credit breaks the running balance, the credit total, and the net reconciliation at once. |
| `demo/02_statement_tampering/tampered_debit_removed.pdf` | REJECTED | A zeroed-out debit breaks the running balance starting at that exact row. |

### Cross-document identity corroboration (Document bundle tab, submit every file in a bundle folder together)

| Bundle | Verdict | Proves |
|---|---|---|
| `demo/04_full_bundle_clean_match/` | REVIEW or APPROVED | Statement, Aadhaar, salary slip, and Form 16 all agree on identity and income. |
| `demo/04_full_bundle_identity_mismatch/` | REJECTED | The Aadhaar in the bundle carries a different name from the rest of the documents. A hard identity mismatch floors the verdict regardless of any individual document's own score. |
| `demo/04_full_bundle_tampered_math/` | REJECTED | Same applicant, but the bank statement's closing balance has been edited. |

### In-person escalation, the active tilt challenge (Live capture tab), see section 4.

### Interpretability: the narrator and underwriter copilot

Once a verification finishes, the console can explain the result in plain English and answer
follow-up questions, without that explanation ever being able to change the verdict (see
[ADR-006](architecture/ADR-006-interpretability-and-resilience.md)).

- **Narrator**: renders the evidence pack as a short plain-English summary covering what was
  analyzed, the key findings translated out of jargon, and the recommended action.
  `POST /api/interpret/narrative`.
- **Copilot**: answers questions like "why was this rejected?" using read-only tools over the frozen
  evidence pack. `POST /api/interpret/ask`. Frontend panel:
  `frontend/src/components/Console/CopilotPanel.tsx`.

What proves it can't lie: a firewall always overrides the narrative's stated verdict with the real
deterministic one and discards any narrative whose recommendation contradicts it. If the underlying
LLM call fails, it falls back to a deterministic narrative instead of erroring out. The narrator and
copilot can run on a different text model than the document reader (`SATYUM_INTERPRET_*`), useful if
your document reader is a vision model that can't also serve as a good conversational narrator.

### Password-protected PDFs

Government and bank PDFs (Aadhaar, CAMS/Karvy statements, signed e-statements) often ship encrypted.
Submitting one returns `{"needs_password": true}`, not an error and not a fraud signal. Resubmitting
with the password (the `pdf_password` field on `/api/verify`) decrypts it in memory without ever
re-saving the file, which matters because a signed-then-encrypted PDF still needs to verify against
its original signature, and re-saving with a third-party tool would destroy that signature. Covered
end to end in `backend/tests/test_pdf_password.py`.

### Misparse-resistant arithmetic

On a real multi-page statement, if the deterministic OCR fallback misreads a balance cell (a stray
digit next to a lakh-scale number), Satyum drops the obviously off-scale figure instead of letting it
cascade into a false rejection. A total misparse resolves to not evaluated, which routes to review,
while a genuinely tampered figure still gets flagged. See `backend/tests/test_arithmetic.py`.

## 4. The live-camera demo

The camera path exists for wet-ink or contested physical documents in person, it is not the primary
path for financial statements. It's wired end to end: the browser streams downscaled frames over a
WebSocket, the server issues a randomized tilt instruction, and the active-challenge analyzer checks
the realized motion against that instruction using homography. Frames are processed in memory and
never saved to disk.

To run it:
1. Open the Live capture tab, start a session, and grant camera permission.
2. Hold a printed, text-bearing document in frame. A printout of one of the demo statements works
   well, the tracker needs visible texture, a blank sheet won't track.
3. Read the on-screen instruction, for example "tilt the document's left edge toward the camera about
   20 degrees, and hold." Perform that tilt deliberately and hold it while the countdown runs.
4. After a few seconds the server scores the attempt and the verdict appears, along with the measured
   tilt versus the commanded one.

What proves it's real:
- Holding still or tilting the wrong way produces "challenge unmet." The verdict tracks your actual
  motion.
- Pointing the camera at a photo of a document on another screen breaks the single-homography
  consistency check (the bezel and the double layer of perspective give it away) and gets flagged as
  a screen replay.
- The challenge axis and magnitude are randomized per session, so a pre-recorded clip can't satisfy a
  command that didn't exist when it was recorded.

Stated honestly: this defeats presentation replay (a printed photo, a phone screen), not a virtual
camera feed injecting fake video at the OS level. That would need platform-level attestation and is a
separate, lower-weight, openly documented check.

## 5. Proving it isn't faking anything

This is worth walking through with a skeptical evaluator. The decision layer is deterministic: rules
recompute the document's own arithmetic, and the verdict moves with the input.

Live, in front of them:
- Open any genuine demo statement in an image or PDF editor, change one balance figure, save it, and
  drag it in. The verdict flips to REJECTED and the finding names the new broken figure. The output
  moves with the input, it's recomputing the math, not pattern-matching against a known-bad list.
- Drag the genuine and the tampered version back to back and watch the verdict flip.

In the test suite, every detector ships with a genuine-versus-adversarial pair and the fraud system
has dedicated must-fail fixtures:
```bash
cd backend && source .venv/bin/activate
python -m pytest -q                                       # full suite
python -m pytest tests/test_constant_return_guard.py -v   # proves a constant-return analyzer fails
python -m pytest tests/test_camera_ws.py -v                # live-capture path, end to end
python -m pytest tests/test_signature.py -v                 # appended-bytes must fail, self-signed must not verify
```
The rule the suite enforces (see `CLAUDE.md` section 3.2): if you replaced any analyzer with
`return <constant>`, its test would fail, because a constant output can't pass a genuine document and
flag a forged one at the same time.

The full synthetic corpus is regenerable from scratch, nothing in it is a hand-edited binary:
```bash
python samples/generate.py
python samples/generate_real_corpus.py
python scripts/generate_full_bundles.py
```

## 6. The security spine, in short

- Full chain-to-pinned-anchor signature validation, byte-range coverage checks, and detection of
  bytes appended after signing, not just "a signature is present."
- Fail closed everywhere. Any error, timeout, or indeterminate result degrades to REVIEW, never
  auto-approve. One analyzer crashing never crashes the overall verdict.
- A hash-chained, tamper-evident audit log. `/api/health` reports whether the chain is intact;
  editing any past record breaks the chain at that point.
- Camera frames live in memory for the session only and are never persisted. No document content or
  personal data is written to logs. Password-protected PDFs are decrypted in memory only, for the
  duration of the request.
- The narrator and copilot are read-only and firewalled off the verdict. Any narrative that
  contradicts the real decision gets discarded before it reaches the user.
- No model sits in the decision path. The vision-language model is treated as untrusted input with
  zero decision authority; cryptography, arithmetic, and rule logic set the verdict, and the same
  claim graph with the same configuration always produces the same, fully traceable result.

---

Verdicts above were observed end to end against the trust anchor in `samples/trust/`. Scores are
deterministic given the same configuration.
