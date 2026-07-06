# Demo documents

This folder holds a small, curated set of test documents for live demos. Everything here is
synthetic or generated from public sample templates. There is no real person's data in this folder.

Every file is also reproducible: run `python samples/generate_real_corpus.py` and
`python scripts/generate_full_bundles.py` from the repo root and they get rebuilt from scratch.

## 1. Signature verification (`01_signature_verification/`)

Upload these one at a time in the File upload tab. They walk through the four ways a PDF signature
can go:

| File | What it shows | Expected verdict |
|---|---|---|
| `genuine_signed.pdf` | A PDF signed by a certificate that chains to the pinned demo root | APPROVED, source-verified |
| `attacker_self_signed.pdf` | Signed, but by a certificate nobody trusts | REVIEW (signature intact, issuer not pinned, not treated as tampering) |
| `appended_after_signature.pdf` | Signed, then extra bytes were appended afterward | REJECTED, tampered |
| `unsigned.pdf` | No signature at all | REVIEW, falls through to document analysis |

The distinction between the second and third row is the one worth explaining out loud: a document
signed by an untrusted issuer isn't proof of fraud, it just isn't verified. Only the appended-bytes
file has actually been altered after signing.

## 2. Statement tampering (`02_statement_tampering/`)

A real Canara Bank statement layout, genuine and then edited one figure at a time. Each tampered
version breaks a different arithmetic invariant.

| File | Edit | Expected verdict |
|---|---|---|
| `genuine_statement.pdf` | None | APPROVED (or REVIEW if unsigned, this one has no digital signature) |
| `tampered_closing_balance.pdf` | Closing balance changed | REJECTED, closing balance doesn't match the running total |
| `tampered_salary_inflate.pdf` | One salary credit inflated | REJECTED, running balance and totals both break |
| `tampered_debit_removed.pdf` | One debit entry zeroed out | REJECTED, running balance breaks at that row |

Good talking point: drag in the genuine file first, then the tampered one, and open the arithmetic
finding. It names the exact row and the exact rupee amount that doesn't reconcile.

## 3. Identity corroboration (`03_identity_corroboration/`)

Use these in the Document bundle tab alongside a statement, or compare two Aadhaar cards directly.

| File | What it shows |
|---|---|
| `aadhaar_genuine.pdf` | A clean identity document |
| `aadhaar_name_mismatch.pdf` | The name differs from the genuine version |
| `aadhaar_number_typo.pdf` | A single digit changed in the Aadhaar number |

Pair `aadhaar_genuine.pdf` with a statement bearing the same name for a clean corroboration, and pair
`aadhaar_name_mismatch.pdf` with it for a hard identity mismatch.

## 4. Full underwriting bundles (`04_full_bundle_*/`)

Each folder is a complete loan-application bundle: bank statement, Aadhaar, salary slip, and Form 16
for the same fictional applicant. Submit all four files in a folder together in the Document bundle
tab.

| Folder | Story | Expected verdict |
|---|---|---|
| `04_full_bundle_clean_match/` | Everything is consistent | REVIEW or APPROVED, corroborated identity and income |
| `04_full_bundle_tampered_math/` | Same applicant, but the bank statement has an edited balance | REJECTED, arithmetic finding names the figure |
| `04_full_bundle_identity_mismatch/` | The Aadhaar name doesn't match the rest of the bundle | REJECTED, identity mismatch across documents |

These are the best set to run end to end for judges: they show provenance, arithmetic, and
cross-document corroboration all firing on one realistic-looking application.

---

For the full test corpus used by the automated test suite (including edge cases like corrupted or
oversized files), see [`samples/README.md`](../samples/README.md) and
[`samples/real_corpus/README.md`](../samples/real_corpus/README.md). This folder is a subset picked
for live, in-person demos, not the full regression corpus.
