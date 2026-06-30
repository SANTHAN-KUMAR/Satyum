# ADR-006 — Interpretability and Ingestion Resilience

> **Status:** Accepted · 2026-06-30 · implemented and tested.
> This records three additions made this cycle. None of them touches the determinism boundary: (a) an
> interpretability layer that explains a verdict it can never change, (b) password-preserving in-memory
> PDF decrypt for the encrypted government and bank documents that are the real-world norm, and (c) an
> arithmetic cross-read gate that stops a parser error from being read as tampering.
> **Builds on** [ADR-004](ADR-004-v2-progressive-evidence-architecture.md) (the determinism boundary that
> none of this crosses: "the model reads; rules decide") and its VLM trust boundary
> ([ADR-004 §5](ADR-004-v2-progressive-evidence-architecture.md)). Honours
> [CLAUDE.md §3](../CLAUDE.md) (no fake signals; honest gates).

---

## 1. Context: three gaps between a correct verdict and a usable one

The v2 spine (ADR-004) already produces a correct, deterministic, fully traceable verdict. Three gaps
remained between *correct* and *usable by a real underwriter on real documents*:

1. **Explainability is structured JSON, not prose.** The evidence pack is reconstructable down to the
   signal, but an underwriter wants "what does this mean, and what do I do?" in plain English, plus a way
   to ask follow-up questions, without that explanation ever being able to move the verdict.
2. **Real government and bank PDFs ship password-locked.** The Aadhaar PDF from myAadhaar, CAMS and Karvy
   CAS, and most signed bank e-statements are encrypted by default. Naively this looks like an unparseable
   file and fails closed, rejecting a legitimate document. The obvious workaround, a third-party password
   remover, destroys the digital signature and defeats Tier-1.
3. **A parser misread can look like a tamper.** On a real 7-page statement, when the VLM read was
   unavailable, the deterministic text-layer parser misread one balance cell (a bare `1` among
   lakh-scale balances). The arithmetic engine then flagged the parser-created inconsistency and falsely
   rejected a genuine document, which is the cardinal §3.3 error of chasing a result that was really an
   extraction bug.

Each is a real-world resilience gap, not a new capability for its own sake.

---

## 2. Decision A: an interpretability layer that explains but never decides

A new `interpretability/` module turns the immutable evidence pack into underwriter-facing language,
behind a structural firewall so it can never become a back door into the verdict.

- **Narrator** ([`narrator.py`](../backend/interpretability/narrator.py)): a single LLM call renders the
  evidence pack as a three-paragraph plain-English summary (what was analysed and the verdict; the key
  findings translated out of jargon; the recommended action). Temperature 0. PII is masked from the pack
  before the call.
- **Underwriter copilot** ([`copilot.py`](../backend/interpretability/copilot.py)): an interactive Q&A
  turn that answers questions using MCP-style tool calls over the frozen evidence pack
  ([`tools.py`](../backend/interpretability/tools.py): `get_signal_detail`, `get_evidence_regions`,
  `get_provenance_detail`, `get_overall_verdict`, `get_network_intelligence`). The model is given the
  verdict as context and must fetch every other fact through a read-only tool. It never authors data.

### The firewall: the load-bearing security property

The interpretation LLM can never change a verdict; it can only explain one. This is enforced
structurally in [`firewall.py`](../backend/interpretability/firewall.py), not by trusting the model:

- The reported verdict is always overridden with the true deterministic verdict from the evidence pack.
  The narrative's own claim of the verdict is discarded.
- Any narrative whose recommendation contradicts the verdict (suggesting approval of a `REJECTED` case,
  or rejection of an `APPROVED` one) is discarded and replaced with a deterministic narrative.
- On any LLM failure (transport error, empty or invalid response, schema mismatch) the layer degrades to
  a purely deterministic narrative built from the structured reasons already in the pack
  ([`fallback.py`](../backend/interpretability/fallback.py)), fail-safe per [CLAUDE.md §4](../CLAUDE.md),
  and flagged `is_fallback=true`.

This keeps the layer on the explanation side of ADR-004's read-versus-decide split. A fully
prompt-injected narrator can at worst be discarded, never approve a fraud.

### Decoupling the interpreter from the vision reader

The interpretation LLM is decoupled from the document-reading VLM through new configuration
(`SATYUM_INTERPRET_PROVIDER`, `_MODEL`, `_API_KEY`, `_BASE_URL`,
[`mcp_client.py`](../backend/interpretability/mcp_client.py)). When these are unset the layer reuses the
`vlm_*` reader credential, so a single-key deployment still narrates.

This lets a text-only reasoner narrate while a separate vision model reads, since the two jobs have
different best-in-class models. DeepSeek v4 (`deepseek-v4-pro`) is wired here as the text narrator. Note
the honest constraint: DeepSeek's hosted API is text-only and rejects images, so DeepSeek serves as the
narrator and copilot, never as a document reader. (DeepSeek-VL2 is open-weights and would need
self-hosting to read documents; that is out of scope here.)

**Tested:** [`tests/test_interpretability.py`](../backend/tests/test_interpretability.py) covers the
firewall (a contradicting narrative is discarded; the true verdict always wins) and the configuration
decoupling (`interpret_*` resolves independently and falls back to `vlm_*` when unset).

---

## 3. Decision B: password-preserving in-memory PDF decrypt

Encrypted PDFs are detected at the intake boundary and handled as a recoverable prompt, not a fraud
signal and not an error.

- [`verification/pdf_crypto.py`](../backend/verification/pdf_crypto.py) provides `is_pdf_encrypted()`
  (fail-safe: only a genuinely password-protected, parseable PDF diverts) and `password_unlocks()`
  (reject a wrong password cleanly before any analyzer runs). Both are cheap, pure pikepdf checks.
- The verify route ([`app/routes/verify.py`](../backend/app/routes/verify.py)) returns a
  `PasswordRequired` response (`needs_password=true`, [`app/contracts.py`](../backend/app/contracts.py))
  when the upload is encrypted and no password, or a wrong password, was supplied. The applicant enters
  the password in-app and resubmits. The password rides on the request as `AnalysisContext.pdf_password`,
  held only for that request and never logged or persisted ([CLAUDE.md §10](../CLAUDE.md)).
- Every consumer decrypts in memory (the signature reader, page renderer, structure parser, OCR,
  metadata, and provenance) and never re-saves the file.

### Why in-memory decrypt is the differentiator

A third-party "remove password" tool re-saves the PDF, which changes the bytes the digital signature
covers and destroys the signature. In-memory decrypt preserves the original signed bytes, so Tier-1
verification still works. This was verified empirically: a signed and encrypted PDF (built in the real
issuance order of encrypt, then sign) verifies as intact and chains to the pinned anchor after in-memory
decrypt, whereas the third-party re-save path breaks it.

**Tested:** [`tests/test_pdf_password.py`](../backend/tests/test_pdf_password.py) (9 tests): the signature
survives in-memory decrypt, a wrong password is rejected, no password yields `PasswordRequired` rather
than a fraud signal, and the decrypted bytes leave the signed content unchanged.

The frontend collects the password inline. When the API returns `needs_password`, the onboarding flow
([`OnboardingFlow.tsx`](../frontend/src/pages/onboarding/OnboardingFlow.tsx)) shows a password field and
resubmits with the password ([`client.ts`](../frontend/src/api/client.ts) raises a typed
`PasswordRequiredError` the UI catches).

---

## 4. Decision C: the arithmetic cross-read gate

The arithmetic engine now distinguishes a likely misparse from a plausible edit, so an extraction error
can never produce a confident "tampered" verdict.

- [`forensics/arithmetic.py`](../backend/forensics/arithmetic.py) computes the statement's monetary scale
  (the median balance) once, robust to a single garbage cell. A running-balance break whose printed
  figure is implausibly off-scale (below `scale × arithmetic_misparse_ratio`) is treated as a parse
  error: it is dropped and does not cascade, because the engine re-anchors on the computed value rather
  than the garbage cell. One misparse cannot manufacture a downstream "plausible" break.
- If there are no plausible breaks but some figures were off-scale misparses, the result is
  `NOT_EVALUATED` (pending, then REVIEW): "could not reliably read it", never a confident tamper. A
  plausible edited figure (a real tamper, at scale) still stays flagged.
- The threshold lives in configuration: `arithmetic_misparse_ratio` (`SATYUM_ARITHMETIC_MISPARSE_RATIO`),
  default 0.5%, marked `# DEFAULT — needs calibration`. It is conservative, so only obvious garbage is
  excused and plausible edits still flag.

The result: the real 7-page genuine statement now correctly resolves to REVIEW instead of REJECTED, and
tamper detection is unchanged (a plausible single-field edit still breaks an invariant and is localised).
The cross-read-verified VLM claim-graph path remains the authoritative arithmetic when available; this
gate is the safety net for the deterministic text-layer fallback.

**Tested:** added to [`tests/test_arithmetic.py`](../backend/tests/test_arithmetic.py): an off-scale
misparse resolves to `NOT_EVALUATED`, a plausible edit still flags, and a dropped misparse does not
cascade.

---

## 5. Why none of this crosses the determinism boundary

All three additions are positioned so they cannot move a verdict toward APPROVE or falsely toward REJECT:

| Addition | Where it sits relative to the verdict |
|---|---|
| Interpretability (narrator and copilot) | Downstream and read-only. Explains a finished verdict; the firewall discards any narrative that contradicts it and always shows the true verdict. A prompt-injected narrator is discarded, never obeyed. |
| Password decrypt | Upstream and mechanical. Makes a legitimate encrypted document readable without altering its bytes; preserves, never weakens, Tier-1. A wrong or absent password yields a recoverable prompt, not a pass. |
| Misparse gate | Inside Layer 4, strictly fail-safer. Converts a parser-induced false REJECT into an honest `NOT_EVALUATED` or REVIEW; a real (plausible) tamper still flags. It can only move a verdict toward review, never toward approve. |

This is the same property ADR-004 and ADR-005 rely on: capabilities are added at the soft and mechanical
edges, while APPROVE and REJECT authority stays with cryptography, `Decimal` rules, and logic.

---

## 6. Honest status and relationship to ADR-004

- **Implemented and tested:** the interpretability firewall, narrator, copilot, and decoupled config; the
  password detect and validate path plus in-memory decrypt across every consumer, with the inline
  frontend prompt; the arithmetic misparse gate. Each ships its own discriminative tests (§2 to §4).
- **Does not amend ADR-004's determinism boundary.** It is defined by it. The interpretation LLM is an
  explanation layer with zero decision authority; the misparse gate only fails safer; the password path
  only makes a real document readable. Any future move to let the interpreter influence a verdict would
  require superseding [ADR-004 §2](ADR-004-v2-progressive-evidence-architecture.md), which this ADR does
  not do.
- **Integrity note ([CLAUDE.md §3](../CLAUDE.md)):** the narrator must always be presented as an
  explanation of the deterministic verdict, never as a participant in it; the password prompt is a UX
  affordance, never a verification signal.
