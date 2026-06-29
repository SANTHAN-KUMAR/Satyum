# ADR-004 — Satyum v2: Progressive-Evidence Document Intelligence (VLM Understanding + Deterministic Decisioning)

> **Status:** Accepted · 2026-06-29 · **the authoritative architecture of record.**
> **Supersedes/amends:** the "no-ML-anywhere / classical-only" stance of [ADR-003](ADR-003-innovation-thesis.md) §"what this commits us to" and the determinism-as-implemented claims of [CLAUDE.md §11/§4].
> **Builds on (unchanged):** [ADR-001](ADR-001-dual-mode-and-signal-validity.md) (mode-tagging, signal-medium validity), [ADR-002](ADR-002-provenance-first-verification.md) (provenance-first waterfall, fail-closed). **Grounded by:** [RESEARCH-001](RESEARCH-001-industry-landscape.md) — which already endorses every v2 choice.
> **This is the reference for building the v2 POC.** Read it fully before refactoring code.

---

## 0. TL;DR — what changes from v1, and what does not

**v1 thesis (ADR-003):** *a forger can fake pixels but cannot keep the logic coherent* → recompute arithmetic invariants deterministically; **no black-box model anywhere**, because determinism = auditability = bank-defensibility.

**What v1 got right and we keep:** provenance-first; the arithmetic/consistency engine as a primary tamper signal; cross-document corroboration; resubmission memory; fail-closed; mode-tagging; the tamper-evident audit; the explainable evidence console; the integrity charter ([CLAUDE.md §3](../CLAUDE.md)) **in full**.

**What was actually fragile in v1 (the re-diagnosis):** *not* the determinism — that is the crown jewel, and [RESEARCH-001](RESEARCH-001-industry-landscape.md) §3 explicitly endorses "OCR + running-balance arithmetic" as trusted, high-signal, robust. The real weakness is the **template-brittle extraction** feeding it. [`forensics/ocr.py`](../backend/forensics/ocr.py) hardcodes one `Date│Description│Debit│Credit│Balance` layout via a fixed synonym list + geometric column bucketing; its own honest bound (lines 27–30) concedes that "multi-line descriptions, merged/rotated cells, and exotic layouts … degrade to … NOT_EVALUATED." So on most real-world statements (other banks, scanned paper, vernacular, images) the powerful engine **never gets to run**. The determinism wasn't too rigid; the *mouth feeding it* was too narrow.

**v2 thesis:** **the model reads; deterministic rules decide.** A vision-language model (VLM) replaces the brittle template parser as an *understanding* layer that reads arbitrary layouts into a **canonical claim graph**; the **decision path stays deterministic, auditable, and fail-closed** — now operating on normalized claims instead of one hardcoded layout. This is strictly *more* defensible than either pure-ML (unauditable, fakeable) or v1's pure-rules (template-starved): the bank story becomes *"a model reads the document, but every number it reports is box-grounded and independently re-verified, and a deterministic rule engine — not the model — decides."*

**The one principle that genuinely evolves:** v1 said "no ML in the decision path." v2 says "no ML in the **decision** path **— and the VLM that reads is an untrusted, grounded, cross-verified input, never a judge.**" Determinism moves from *pixels→verdict* to *claims→verdict*; we acknowledge that honestly (§5.6) rather than pretend end-to-end determinism survives a hosted model.

---

## 1. Definition

> **Satyum is a zero-trust, progressive-evidence document-intelligence engine for underwriting.** It does not claim to detect every fake. It **extracts** claims from arbitrary documents, **verifies** what can be verified (cryptographic provenance first), **flags contradictions** with deterministic domain rules, **detects** suspicious patterns as soft signals, **corroborates** claims across the evidence bundle, and **fails closed** — routing to human review — when evidence is insufficient. Every decision is reconstructable from box-grounded claims, signed rule outputs, and a tamper-evident audit trail.

It remains, at its core, a **cybersecurity system**: applied cryptography/PKI, a threat-modeled fail-closed pipeline, defensive ingestion of hostile files, an injection-resistant capture mode, and a hash-chained audit — now hardened against a new attack surface the VLM introduces (§5).

---

## 2. The core principle — "the model reads; deterministic rules decide"

Three tiers of trust, structurally separated:

| Tier | Component | Trust posture | Determinism |
|---|---|---|---|
| **Source of truth** | Provenance / signature / PKI (Layer 1) | **Authoritative** when present | Fully deterministic |
| **Understanding** | VLM extraction → claim graph (Layers 2–3) | **Untrusted input** — grounded + cross-verified | Probabilistic, *bounded* |
| **Judgment** | Ontology rules, corroboration, decision brain (Layers 4, 6, 7) | **Deterministic authority** | Fully deterministic given the claim graph |

The VLM has **zero decision authority**. It may never output "genuine" or "fake," may never set a verdict, and may never see an expected value. Its sole product is *typed, box-grounded, confidence-scored claims that are then independently re-verified*. This is not a style choice — it is the security control that neutralizes the VLM's failure modes (hallucination-laundering and prompt injection; §5).

---

## 3. The pipeline (Layers 0 → 7 → console/loop)

```
Single document │ case context │ optional source/bundle
        ↓
0. Intake + Evidence Sufficiency      (what doc, what quality, what confidence is possible)
        ↓
1. Provenance / Source Verification   (crypto first — authoritative when present)   ← KEEP v1, harden
        ↓
2. VLM Document Understanding         (read arbitrary layouts → fields/tables + bbox + conf)  ← NEW
        ↓
3. Canonical Claim Graph              (typed claims; template-independent)           ← NEW
        ↓
4. Domain Ontology + Rule Packs       (deterministic PASS/FAIL/UNKNOWN/N-A/N-E)      ← KEEP arithmetic, generalize + add land/legal
        ↓
5. Anomaly Intelligence (hybrid)      (deterministic stats backbone + optional ML lane; soft REVIEW-only)  ← NEW (hybrid)
        ↓
6. Cross-Document / Cross-Source Corroboration  (claims agree across the bundle/sources)  ← KEEP v1 cross-doc, extend
        ↓
7. Final Decision Brain               (guarded fail-closed policy → APPROVE/REVIEW/REJECT/PENDING)  ← KEEP v1 risk engine, formalize guards
        ↓
Evidence Console + Human Review + Rule-Learning Loop
```

Each layer below: **Purpose · How it works · Tools/platforms · Disposition (keep/new/harden) · Honest bound.**

### Layer 0 — Intake + Evidence Sufficiency *(NEW, lightweight)*
- **Purpose:** classify document type, gate quality, and decide *what confidence is even achievable* — `single-document` / `case-context` (doc + application fields) / `corroborated` (doc + salary slip/Form-16/ITR/AA/registry). This makes "I only got one PDF" an explicit, honest state, not a silent assumption.
- **How:** magic-byte sniff + size/MIME guards (already in [`verify.py`](../backend/app/routes/verify.py)); PyMuPDF render; a **doc-type classifier** (VLM zero-shot prompt *or* a small deterministic header/keyword classifier — both behind one interface); quality gate (reuse the Laplacian-variance focus gate from [`rectify.py`](../backend/capture/rectify.py)).
- **Tools:** FastAPI, PyMuPDF, the `VLMExtractor` (classification call) or a keyword classifier, OpenCV.
- **Output:** `{doc_type, quality, evidence_level, achievable_confidence}` → feeds the decision brain's sufficiency gate.
- **Honest bound:** `UNKNOWN` doc type and `insufficient` evidence are first-class outputs that route to REVIEW, never to a guessed pass.

### Layer 1 — Provenance / Source Verification *(KEEP v1 wholesale; harden)*
- **Purpose:** verify the document's cryptographic source before trusting its bytes — the strongest, most authoritative layer. Verified ≠ a pixel guess; it is math.
- **How (already real — see the v1 audit):** PAdES/CMS via **pyHanko** against a pinned `trust_roots`; a signature counts as verified only when `intact ∧ valid ∧ trusted ∧ coverage == ENTIRE_FILE` ([`signature.py:198`](../backend/verification/signature.py#L198)) — catching attacker-cert chains, appended-bytes/shadow attacks, broken digests. **C2PA** trust-list-pinned. PDF structure/incremental-update detection ([`metadata.py`](../backend/forensics/metadata.py)). "PDF-only when a source pull was possible" red flag.
- **Tools:** pyHanko, pyhanko-certvalidator, cryptography, asn1crypto, c2pa-python, pikepdf.
- **Result contract:** `VERIFIED_SOURCE` (strong trust floor) · `TAMPERED` (reject) · `NO_SOURCE` (→ fallback) · `SOURCE_AVOIDED` (risk signal).
- **HARDEN (carry-over work):**
  1. **Drop the real CCA-India root** into [`trust_anchors/`](../backend/verification/trust_anchors/) — today it ships empty and only the self-signed `samples/trust/demo_ca_root.pem` exists. This is *the* load-bearing gate to make Layer 1 production-true.
  2. Add **CRL/OCSP revocation + embedded-timestamp** validation (currently `allow_fetching=False`); fail-closed on unreachable revocation.
  3. Derive the issuer for the PDF-only red flag **from the document**, not the client-supplied `issuer_hint` form field (today trivially evadable, [`verify.py:84`](../backend/app/routes/verify.py#L84)).
- **v2 CHANGE — do not over-short-circuit:** in v1, `verified` jumps the score to 99 and **excludes all forensics**. In v2, `VERIFIED_SOURCE` sets a **high floor but the claims still flow into the corroboration brain (Layer 6).** Provenance proves *byte-authenticity, not claim-truthfulness* — a cryptographically genuine statement can still carry an income that contradicts the ITR or come from a shell account. (RESEARCH-001 §6: provenance is "a strong signal, not absolute proof" — Nikon Z6 III exploit, c2patool, the first-mile gap.)
- **Honest bound:** "verified" means origin authenticity, never a fraud verdict on content.

### Layer 2 — VLM Document Understanding *(NEW — the headline change; see §5 for the trust boundary)*
- **Purpose:** read *arbitrary* layouts — any bank's statement, scanned paper, image, vernacular, deed, agreement — into typed fields and tables, each with `page + bbox + confidence`. This is the layer that widens the mouth so Layer 4's deterministic rules actually run on real-world documents.
- **How:** a single **`VLMExtractor` interface** (`extract(image, schema) -> list[Claim]`) with two implementations:
  - **POC default — cloud:** a frontier multimodal model behind the interface, called with a **structured-output / tool-use schema** (typed fields only, no free text), **temperature 0**, and the **bounding box + confidence per field required by the schema**. Recommended default: **Claude Sonnet 4.6** (fast, strong structured doc extraction, cheap per page) with **Claude Opus 4.8** as the high-accuracy lane for hard/contested docs; **Gemini 2.x** is a drop-in alternative. *Model id + prompt hash are logged into the audit chain.*
  - **Production swap — self-hosted:** **Qwen2.5-VL-7B-Instruct** (or InternVL2.5) served via **vLLM** inside the bank perimeter — data never leaves, model is pinned/reproducible. Same interface, config flag swap, no code rewrite. (This is the DPDP-clean answer; the cloud POC is the fast-to-strong answer. The interface is what makes the swap a non-event.)
- **Tools:** `anthropic` (or `google-genai`) SDK for cloud; vLLM + Qwen2.5-VL for self-host; Pydantic schema for the structured output; PyMuPDF render; **Tesseract / PaddleOCR for the numeric cross-read (§5.2)**.
- **Disposition:** the existing [`forensics/ocr.py`](../backend/forensics/ocr.py) Tesseract table-parser is **demoted to the cross-read verifier**, not deleted — its deterministic digit-reading is exactly what re-checks the VLM's numbers.
- **Honest bound:** the VLM is the system's only probabilistic component; §5 is the entire reason it is safe to use in a fraud system. It outputs claims, never judgments.

### Layer 3 — Canonical Claim Graph *(NEW — the decoupling that makes v2 work)*
- **Purpose:** collapse every layout into one internal structure so the rules are **template-independent**. SBI, Canara, HDFC, a phone photo of a deed, a vernacular RoR — all become the same typed claims.
- **How:** every extracted value becomes a `Claim`:
  ```
  Claim(subject, predicate, value, value_type,
        provenance=ClaimProvenance(doc_id, page, bbox, confidence,
                                   source="vlm",
                                   corroborating_read=<deterministic OCR value | None>,
                                   cross_read_agree: bool))
  ```
  e.g. `(bank_statement_1, has_running_balance[row=7], 84,200.00, MONEY, …)`, `(sale_deed_1, has_seller, "Ramesh Kumar", NAME, …)`. The graph spans the whole bundle, so Layer 6 is just graph queries.
- **Tools:** typed Pydantic/dataclass `Claim` contract (extends the [`contracts.py`](../backend/app/contracts.py) family); an in-memory typed graph (plain dicts/lists; `networkx` only if/when traversal complexity warrants — YAGNI until then).
- **Honest bound:** a claim with `cross_read_agree=False` or `confidence < gate` is carried as **`NOT_EVALUATED`/pending**, never silently trusted.

### Layer 4 — Domain Ontology + Rule Packs *(KEEP v1 arithmetic; generalize; ADD land/legal)*
- **Purpose:** the deterministic *judgment* layer. Encode each domain's invariants as rules over the claim graph; every rule returns one of `PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NOT_EVALUATED` — so missing context never becomes fake confidence. The typed vocabulary, predicates, and **machine-readable axioms** for all three domains live as JSON rulebooks the engine loads and computes from — **[`backend/ontology/`](../backend/ontology/)** (one file per domain + a shared `check_kinds` catalog the engine dispatches on, documented in its [README](../backend/ontology/README.md)).
- **How:** a **mode-of-the-domain rule-pack registry** mirroring the existing analyzer registry pattern ([`registry.py`](../backend/app/registry.py)). Each pack is a set of pure functions over claims:
  - **Financial pack *(production depth — REHOMED from [`arithmetic.py`](../backend/forensics/arithmetic.py))*:** running-balance chain (re-anchored per printed balance), closing balance, column totals, net reconciliation — **now reading the claim graph instead of `StatementData`** — plus `net_salary = gross − deductions`, `salary-slip net ≈ bank salary credit`, `Form16/ITR income ≈ observed income`.
  - **Land/title pack *(real-but-scoped)*:** seller ↔ prior/current owner (where a RoR claim exists), `registration_date ≥ execution_date`, survey/khata/property-ID consistency, extent/unit conversions, stamp-duty/value where a state table exists.
  - **Legal/contract pack *(real-but-scoped)*:** party names consistent across body/signature/schedule, `amount_in_words == amount_in_figures`, `start + term == end`, referenced schedules exist, page-numbering complete, signature/witness blocks present.
- **Tools:** pure Python `Decimal` + logic; `rapidfuzz` for name/string matching (already used in [`cross_document.py`](../backend/forensics/cross_document.py)); the rule-pack registry.
- **Depth-tiering (the honest answer to "multi-domain breadth"):** financial is production-depth + adversarially tested; land/legal ship as **genuinely computing** packs that return `NOT_EVALUATED` for any invariant whose claims/state-tables aren't present — real rules with labeled coverage bounds, **never** faked passes. Breadth of *real* rule packs, not breadth of theater.
- **Honest bound:** rules catch *incoherent* forgeries (edits, most GenAI output); a fully recomputed-and-reprinted forgery that satisfies every invariant is covered by Layers 1, 5, 6 — never claimed here.

### Layer 5 — Anomaly Intelligence *(NEW — HYBRID; soft REVIEW-only)*
- **Purpose:** surface *suspicious patterns* (not contradictions) as **soft** risk signals. Anomaly → REVIEW; no anomaly ≠ genuine; insufficient history → `NOT_EVALUATED`.
- **How (hybrid, behind one `AnomalyDetector` interface):**
  - **Deterministic statistical backbone (default, always-on, auditable):** round-number synthetic salary credits, sudden salary jump, short/cherry-picked statement window, dormant-account revival, declared-value-vs-reference gap, spending-pattern breaks. Pure NumPy/pandas statistics — fully explainable to an auditor.
  - **Optional ML lane (pluggable, flag-gated, soft):** a time-series/embedding anomaly model (e.g. a TimesFM-style foundation model or a lighter learned detector) behind the same interface. **Additive only** — it can raise REVIEW, never approve, never reject, never gate. Honestly labeled `experimental` in the console and excluded from the determinism guarantee.
- **Tools:** NumPy/pandas for the backbone; the ML lane behind `AnomalyDetector` (hosted or local; off by default in the POC, on via `SATYUM_ANOMALY_ML_ENABLED`).
- **Honest bound:** every anomaly is REVIEW-only and reason-tagged. The ML lane's contribution is always separable and labeled, so a bank can audit the decision *with the ML lane removed* and get the same APPROVE/REJECT (only REVIEW routing changes).

### Layer 6 — Cross-Document / Cross-Source Corroboration *(KEEP v1 cross-doc; extend)*
- **Purpose:** answer what single-document arithmetic cannot — do the claims agree *across* the evidence? bank salary credits ≈ salary-slip net ≈ Form-16/ITR income ≈ application income; deed seller ≈ RoR owner; property ID matches across deed/RoR/EC; PAN/phone/address/employer not suspiciously reused.
- **How:** the existing [`cross_document.py`](../backend/forensics/cross_document.py) (real, empirically discriminating — same PAN → 0.04, mismatched PAN → 0.92) **extended to consume the claim graph** and more field/source types. Plus the **resubmission/fraud-ring memory** (pHash) — *fix the v1 stub*: seed the [`phash.py`](../backend/forensics/phash.py) store from the durable audit DB so it actually fires in production (today it's an empty in-memory store → never fires).
- **Tools:** the cross-doc engine + `rapidfuzz`; ImageHash (pHash) + the Postgres store; the issuer-capability + fraud-hash tables.
- **Honest bound:** `INSUFFICIENT_CORROBORATION` (single doc, no overlap) → REVIEW, **never approve**; non-overlapping fields → `NOT_EVALUATED` (fail-open on that field, not a false mismatch).

### Layer 7 — Final Decision Brain *(KEEP v1 risk engine; formalize the golden-rule guards)*
- **Purpose:** a guarded, fail-closed policy engine that composes all signals into `APPROVE / REVIEW / REJECT / PENDING`.
- **How:** extend [`risk/engine.py`](../backend/risk/engine.py) (already genuinely fail-closed: NOT_EVALUATED excluded from numerator *and* denominator; ERROR caps at REVIEW; kill-a-layer → REVIEW not APPROVE). The **golden rules become structural invariants**, each with a property test:
  - **VLM alone can never approve** (a verdict with no VALID Layer-1/Layer-4/Layer-6 signal → at most REVIEW).
  - **Arithmetic passing ≠ genuine** (clean rules + no corroboration + no provenance → REVIEW; the existing `substantive_content_signals` gate generalizes to "sufficient corroboration").
  - **Anomaly alone can never reject** (Layer-5 is REVIEW-only).
  - **Missing evidence never becomes a pass** (insufficiency → REVIEW/PENDING).
  - **Tampered provenance / hard ID mismatch / known fraud reuse → REJECT, fail-closed.**
- **Tools:** the existing weighted-mean engine + the audit ledger; config-driven bands (`approve_at=85`, `review_at=60`).
- **Honest bound:** indeterminate aggregates resolve to REVIEW; no single probabilistic signal can move a verdict to APPROVE or REJECT on its own.

### Evidence Console + Human Review + Rule-Learning Loop *(KEEP the console; add review/versioning)*
- **Console (already strong, contract-bound):** extend the React console ([`frontend/src/components/evidence/`](../frontend/src/components/evidence/)) with: a **claim-graph view** (claims + their bbox + VLM-vs-cross-read agreement), **per-domain rule results**, the **corroboration view** (extend the existing CrossDocumentGraph), an **evidence-sufficiency banner**, and **VLM-extraction provenance** (every number shows its box + confidence + "independently re-read: ✓/pending"). Everything still traces to real backend output (the §9 "no fabricated UI data" rule is unchanged).
- **Human review + learning loop:** reviewer flags an edge case → proposes a new ontology/rule → risk/admin approves → the rule is **tested against past cases** → a **versioned** rule is deployed; the audit ledger records *which rule-pack version* produced each verdict. **POC scope:** rule packs are versioned, the audit records the version, and there is a review queue + a "propose rule" capture. Full governance workflow is the documented production path.
- **Tools:** existing React/TS/Tailwind console + TanStack Query; a rule-version registry (Postgres); the audit ledger.

---

## 4. What we keep, harden, rehome, down-weight, and cut (code disposition)

| Component | File(s) | v2 disposition |
|---|---|---|
| Orchestrator, mode-keyed registry, contracts | `app/{orchestrator,registry,registry_assembly,contracts}.py` | **KEEP + EXTEND** — add the `Claim`/claim-graph contract, the rule-pack registry, the VLMExtractor + AnomalyDetector interfaces. |
| Risk engine, evidence pack, audit ledger | `risk/{engine,evidence,audit}.py` | **KEEP + HARDEN** — formalize golden-rule guards; record VLM model id/prompt hash + rule-pack version; wire the audit-chain truncation anchor; enable durable Postgres by default in deploy. |
| PAdES signature, C2PA, PDF structure | `verification/signature.py`, `verification/provenance.py`, `forensics/metadata.py` | **KEEP + HARDEN** — real CCA root, CRL/OCSP + timestamp, document-derived issuer. Stop over-short-circuiting corroboration. |
| Arithmetic consistency engine | `forensics/arithmetic.py` | **KEEP + REHOME** — becomes the Financial rule pack; consumes the claim graph instead of `StatementData`. The crown jewel, unchanged in spirit. |
| OCR table parser | `forensics/ocr.py` | **DEMOTE → cross-read verifier** — its deterministic digit-reading re-checks VLM numbers (§5.2); no longer the primary extractor. |
| Cross-document graph | `forensics/cross_document.py` | **KEEP + EXTEND** — consume the claim graph; more field/source types. |
| pHash resubmission | `forensics/phash.py` | **KEEP + FIX STUB** — seed the store from the audit DB so it fires in production. |
| Entity extraction / Aadhaar Verhoeff | `forensics/entities.py` | **KEEP** — folds into the claim graph + KYC-lite checks; Verhoeff stays a REVIEW-only signal. |
| Font/layout, copy-move, template fingerprint | `forensics/{layout,copy_move,template}.py` | **KEEP, DOWN-WEIGHT to supporting/soft** — RESEARCH-001 trusts structure/metadata + font-alignment but is wary of pixel copy-move; template needs a real corpus or stays `NOT_EVALUATED`. None featured; all soft, mode-tagged. Fix `layout.py` `MIN_OCR_CONF=0.0` comment/behavior mismatch. |
| Tier-3 capture: rectify, active 3D challenge, anti-spoof | `capture/{rectify,challenge,antispoof}.py` | **KEEP, RE-SCOPE** — the in-person escalation for wet-ink/contested *physical* documents and the person (seller/owner), **not** the financial-statement primary path. Mode-tagged. Honest bound: injection-resistant capture is the goal; enforce the challenge TTL server-side; multi-step challenge chain is the depth upgrade. |
| Virtual-camera/sensor check | — | **GATED (unbuilt)** — browser-medium limit; ships no fake PASS. Native-app substitute documented. |
| Pixel-forgery ML (ELA/PRNU/stego/AI-gen freq/GradCAM), micro-expression | — | **CUT — on merit** (RESEARCH-001 §3/§6: near-chance, OOD-collapse on GenAI, unvalidatable; ethics). The VLM is *understanding*, **not** a pixel-forgery detector — this exclusion stands. |

---

## 5. The VLM trust boundary — why it's safe in a fraud system *(the critical section)*

A generative reader in a fraud pipeline has two dangerous, under-appreciated failure modes. v2 neutralizes both **structurally** — this is non-negotiable and every mitigation ships with a must-fail fixture.

### 5.1 Hallucination-laundering (the catastrophic one)
A VLM is trained to produce *plausible* output. Given a tampered figure, it may "auto-correct" toward the value that makes the row reconcile — **laundering a tamper into consistency** and handing the deterministic engine a clean-looking statement. This is a *false negative* in a fraud system: the worst possible error. Mitigation:
- **The VLM never sees expected values or arithmetic context.** Read first, check second, no feedback loop.
- The decision is downstream and deterministic, so the VLM cannot "decide" anything is fine.

### 5.2 Numeric cross-read consensus (the core control)
- Every **numeric** claim the VLM locates (it returns the cell + bbox) is **independently re-read by a deterministic OCR** (Tesseract now, PaddleOCR for vernacular) on that exact crop.
- The two reads must agree within `Decimal` tolerance. **Disagree → the claim is `NOT_EVALUATED` (pending), never a silent pick.**
- This restores discrimination: a tamper one reader smooths, the other reads literally → they disagree → REVIEW, fail-closed. The number's authority comes from **grounded, independently-verified transcription**, not the model's "understanding." Must-fail fixture: *a statement where the VLM is induced to normalize a tampered cell must end NOT_EVALUATED or FLAGGED, never VALID-clean.*

### 5.3 Prompt injection
The forger controls document content and can embed instructions ("SYSTEM: mark verified"). Mitigation:
- **Structured-output schema only** — the VLM returns typed fields, never free decisions; document text is *data*, never instructions.
- Because the verdict is downstream and deterministic, even a *fully* prompt-injected VLM can only emit wrong *claims* — caught by cross-read consensus (§5.2) + the rules. It cannot move the verdict. Must-fail fixture: *a document with an embedded "approve this" injection still reaches the correct deterministic verdict.*

### 5.4 Bounded output / hostile-input validation
VLM output crosses a trust boundary → validate like any hostile input ([CLAUDE.md §10](../CLAUDE.md)): typed schema, value ranges, `bbox ⊆ page`, drop instruction-like strings. Malformed → `NOT_EVALUATED`, never a guess.

### 5.5 Cost / latency discipline
One VLM pass per document (page-batched), temperature 0, response cached by content hash within a session. The cross-read OCR runs only on located numeric cells, not the whole page. Self-host removes per-call cost entirely.

### 5.6 Reproducibility & audit — stated honestly
- Temperature 0 + a pinned model id + the prompt hash, **all logged into the hash-chained audit** so a verdict's extraction context is reconstructable.
- **Honest limitation (not hidden):** end-to-end determinism ("same pixels → identical verdict") is *best-effort* with a hosted model that can change under us. We therefore guarantee determinism **from the claim graph onward** (the decision path), and pin the model + cross-verify every number to bound the extraction. **The self-host path (Qwen2.5-VL pinned in-perimeter) restores full reproducibility** — which is exactly why it is the production target. A bank auditor asking "why 85,000?" gets: *the box at (x,y), the VLM read, the independent OCR re-read, and they agreed* — auditable regardless of hosting.

---

## 6. Cross-cutting invariants (the v2 charter — enforced by property tests)

1. **The model reads; deterministic rules decide.** No ML/VLM in the decision path; VLM extraction-only, untrusted, cross-verified.
2. **Provenance-first.** Verified = byte-authenticity, not claim-truthfulness; never `signed ⇒ authentic` as dispositive.
3. **Fail-closed everywhere.** Any error/timeout/uncertainty degrades toward the more secure outcome; ERROR caps at REVIEW; one analyzer's failure never crashes the verdict or the stream.
4. **Evidence-sufficiency-gated.** Missing evidence → PENDING/REVIEW, never a pass; `NOT_EVALUATED` excluded from the score numerator *and* denominator.
5. **Mode-tagging preserved.** A file-forensic signal can never display as passed on a camera frame; the registry forbids it structurally.
6. **Numeric claims are box-grounded + cross-read-verified** before any rule trusts them.
7. **Tamper-evident audit** of every verdict, its signals, the VLM model id/prompt hash, and the rule-pack version.
8. **No fabricated UI data** — every number on screen traces to real backend output + its claim provenance.
9. **Privacy by design** — document content/imagery never persisted; PII redacted from logs; VLM calls carry the minimum pixels needed and (cloud POC) are flagged as leaving the perimeter; self-host removes that exposure.

---

## 7. Tech stack — specific, with what-uses-what

| Area | Choice | Used by / how |
|---|---|---|
| **Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 | The spine — routes, orchestrator, contracts, all interfaces. Unchanged. |
| **VLM (understanding)** | `VLMExtractor` interface. **Cloud (POC):** Claude **Sonnet 4.6** default / **Opus 4.8** hard-doc lane via `anthropic` SDK (Gemini 2.x alt). **Self-host (prod):** **Qwen2.5-VL-7B** via **vLLM**. | Layer 0 (classify), Layer 2 (extract). Structured outputs, temp 0, bbox+conf per field, model id logged. |
| **Cross-read OCR** | **Tesseract** (`pytesseract`) now; **PaddleOCR** for vernacular | Layer 2 §5.2 numeric consensus; the demoted [`ocr.py`](../backend/forensics/ocr.py) becomes this verifier. |
| **Crypto / provenance** | pyHanko, pyhanko-certvalidator, cryptography, asn1crypto, c2pa-python | Layer 1 — PAdES/CMS to CCA root, C2PA trust-list-pinned. |
| **PDF / parse / CV** | pikepdf (qpdf), PyMuPDF (fitz), OpenCV-headless, scikit-image, Pillow | Layer 0/1/2 render + structure; Tier-3 capture. |
| **Claim graph** | Typed Pydantic/dataclasses (networkx only if needed) | Layer 3 — the `Claim` contract; queried by Layers 4 & 6. |
| **Rules / consistency** | Pure Python `Decimal` + `rapidfuzz` | Layer 4 rule packs (financial/land/legal); Layer 6 corroboration. |
| **Anomaly** | NumPy/pandas backbone + optional ML lane behind `AnomalyDetector` | Layer 5 — deterministic stats default; ML lane flag-gated, soft. |
| **Perceptual hash** | ImageHash (pHash) | Layer 6 resubmission/fraud-ring memory (seeded from audit DB). |
| **Data** | PostgreSQL (audit ledger, fraud-hash/pHash store, issuer-capability registry, rule-version registry) via SQLAlchemy 2.0; **in-memory** ephemeral session/frames (never persisted) | Audit, corroboration memory, rule versioning. Durable audit **on by default** in deploy. |
| **Frontend** | React 18 + TS + Vite, Tailwind, TanStack Query, WebRTC + WS | The evidence console — extended with claim-graph + corroboration + sufficiency views. |
| **Infra** | Docker + docker-compose, Nginx (TLS, `/api` `/ws` `/`), structlog + correlation IDs, healthchecks | Reproducible deploy; the VLM is a config-driven dependency (cloud key *or* vLLM endpoint). |
| **Quality/CI** | pytest (+ must-fail fixtures incl. the new VLM-boundary fixtures), ruff/black/mypy; vitest/Playwright, eslint/prettier | Enforces §3/§8 mechanically; CI gate runs the must-fail fixtures. |

---

## 8. POC build order (multi-domain breadth, depth-tiered)

Per the locked decisions: **cloud VLM (swappable), multi-domain (financial deep + land/legal real-but-scoped), hybrid anomaly.** Build by dependency, not calendar ([CLAUDE.md §2](../CLAUDE.md)):

1. **Spine + contracts:** add `Claim`/claim-graph, `VLMExtractor`, `AnomalyDetector`, rule-pack registry to the existing orchestrator/registry. (Most of the spine already exists and is real.)
2. **Layer 2+3 on financial:** VLM extractor (cloud) → claim graph, with the §5.2 cross-read consensus and §5 must-fail fixtures. This is the highest-risk new code — build and adversarially test it first.
3. **Layer 4 financial pack:** rehome `arithmetic.py` onto the claim graph; add salary/income reconciliation. Re-run the existing hard corpus ([`realistic_fixtures.py`](../backend/tests/realistic_fixtures.py)) through the new path.
4. **Layer 1 hardening:** real CCA root, revocation, document-derived issuer; stop over-short-circuiting.
5. **Layer 6 corroboration:** extend cross-doc onto the claim graph; fix the pHash store seeding.
6. **Layer 7 guards + Layer 0 sufficiency:** formalize the golden-rule invariants; evidence-sufficiency gate.
7. **Layer 5 anomaly:** deterministic backbone (default on); ML lane behind the flag (off in POC).
8. **Land + legal rule packs (real-but-scoped):** real rules, honest `NOT_EVALUATED` coverage bounds.
9. **Console extension + review/versioning loop.**
10. **Tier-3 re-scope** (keep as in-person escalation; not in the financial path).

Every step ends at a genuinely running slice with discrimination tests + the relevant must-fail fixtures ([TESTING-STRATEGY](TESTING-STRATEGY.md)). Anything not built to depth is an **honestly-labeled gate**, never half-wired theater.

---

## 9. What this supersedes / amends (doc map)

- **Supersedes/amends:** ADR-003's "we do not invest in pixel/ML … no black-box model" commitment — narrowed to *"no ML in the **decision** path; the VLM **reads**, never judges."* ADR-003's **consistency-first thesis is otherwise intact and is now Layer 4.**
- **Amends:** [CLAUDE.md §11/§4/§1] determinism-as-implemented claims → "the model reads, rules decide; determinism from the claim graph onward." Integrity charter (§3) unchanged and now **also governs the VLM boundary**.
- **Unchanged:** ADR-001 (mode-tagging, signal-medium validity), ADR-002 (provenance-first, fail-closed), RESEARCH-001 (already endorses v2), the evidence-console standards (§9).
- **Companion specs to update:** [BUILD-MANIFEST](BUILD-MANIFEST.md) (component table → v2), [TESTING-STRATEGY](TESTING-STRATEGY.md) (determinism invariant + VLM-boundary fixtures).

## 10. Open calibration items & honest gates (record, never hide)

- All scoring weights/thresholds remain `# DEFAULT — needs calibration` until run against a real labeled corpus (no invented accuracy numbers — [CLAUDE.md §3.3](../CLAUDE.md)).
- Real CCA-India root, CRL/OCSP, AA/registry live pulls = labeled regulatory/credential gates (real substitutes named).
- VLM end-to-end determinism = bounded, not absolute, on cloud; full on self-host (§5.6).
- Land/legal rule-pack coverage = real but partial; every uncovered invariant returns `NOT_EVALUATED`, surfaced in the console.
- ML anomaly lane = experimental, off by default, separable from the decision.

*Constrained by the integrity charter ([CLAUDE.md §3](../CLAUDE.md)) — which v2 honors in full, and extends to the VLM boundary.*
