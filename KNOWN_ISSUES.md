# Satyum - Known Issues & Troubleshooting Log

This document tracks known architectural edge-cases, API limitations, and deterministic friction points discovered during development and testing. 

Whenever a new issue is encountered, it should be documented here along with its root cause and the resulting system cascade.

---

## 1. VLM API Crash & Deterministic Cascade (JSON Mode Limitation)

**Date Discovered:** 2026-07-01  
**Symptom:** 
Documents get misclassified as "Unclassified" in the Underwriter Console. This causes ID documents (like Aadhaar cards) to be falsely flagged by the Typography engine (`font_layout`) for having anomalous fonts (e.g., mixing English and Hindi scripts). Both the VLM extraction and the LLM interpretability engines fail to produce output.

**Root Cause:**
1. **The VLM Payload:** The Satyum orchestrator requires mathematical and structured extraction from the Vision-Language Model (VLM) to feed the forensic math layers. It enforces this by passing `response_format: {"type": "json_object"}` in the API request.
2. **API Rejection:** Certain fallback Vision APIs (like Groq's `meta-llama/llama-4-scout-17b-16e-instruct`) do not fully support strict JSON mode on their vision endpoints yet. When they receive the JSON flag alongside an image, they instantly reject the payload with a `400 BadRequestError` (regardless of how small the image file size is).
3. **The Unclassified Cascade:** Because the VLM crashes, it never extracts the document type (`doc_class`). The document proceeds down the waterfall as `doc_type: None` (Unclassified).
4. **The Fail-Closed Rule:** The downstream Typography engine (`font_layout`) has an explicit rule to *skip* typography checks for ID cards. Because the document is unclassified, the engine ignores the exemption and applies strict bank-statement-level typographical scrutiny. It spots the mixed scripts (Hindi/English), calculates a high Z-score spike, and correctly (but falsely) flags it as an anomaly.
5. **The LLM Silence:** The Interpretability Engine (LLM) relies entirely on the extracted VLM JSON Claim Graph to narrate the findings. With an empty graph, it skips generation rather than hallucinating.

**Resolution (Implemented):**
- **Per-backend JSON-mode capability.** The VLM extractors now take a `use_json_response_format` flag. The factory ships it **off for Groq** (`meta-llama/llama-4-scout-*`), whose vision endpoint hard-400s on `response_format: json_object` with an image attached. The injection-hardened prompt already demands a bare JSON object and the parser fence-strips + schema-validates the reply, so the trust boundary is unchanged. (`forensics/extraction/{groq_extractor,openai_compatible_extractor,factory}.py`.)
- **Self-healing retry.** Independently of the flag, both readers now catch a JSON-mode `400` (Groq `BadRequestError`; OpenAI-compatible HTTP 400) and **retry once without `response_format`** before failing. This makes the fix provider-agnostic — an unknown backend that rejects strict JSON mode self-heals instead of crashing the extraction and cascading the document to `Unclassified`.
- Covered by discrimination tests in `tests/test_vlm_extraction.py` (§8): disabled-flag omits the field, a JSON-mode 400 retries and succeeds, and a non-JSON-mode 400 still fails closed.
- *Residual (by design):* if **every** reader is genuinely exhausted, the layer still fails closed to `NOT_EVALUATED`/`ERROR` and the document routes to human review — never a fabricated pass.

---

## 2. Cloudflare Free-Tier Quota Exhaustion

**Date Discovered:** 2026-07-01  
**Symptom:** 
When processing a multi-document bundle (e.g., 3-4 documents at once), the backend logs repeatedly show `rate limited / quota exhausted` for the Cloudflare Mistral vision model. The system then cascades to the Groq fallback (which subsequently crashes due to Issue #1). As a result, the entire bundle fails to process correctly.

**Root Cause:**
- The `mistral-small-3.1-24b-instruct` model on Cloudflare Workers AI has a relatively small free-tier quota for token usage.
- A single document extraction with the massive JSON schema prompt consumes a significant number of tokens. Uploading a batch of 3-4 documents simultaneously rapidly burns through the remaining daily quota, resulting in a hard rate limit.

**Resolution (Implemented): Multi-Key Fallback Architecture**
- **The Fix:** The VLM Extractor Factory (`factory.py`) was completely refactored to parse comma-separated API keys from the `.env` configuration. It dynamically generates multiple extractor instances (one for each key) and seamlessly chains them together.
- **Graceful Degradation (Zero-Downtime):** The system now utilizes a massive, unified `FallbackExtractor` sequence structured in three defensive tiers:
  1. **Primary Lane (Gemini):** Rotates through 8 provided Gemini API keys.
  2. **Fallback 1 (Cloudflare):** If all 8 Gemini keys exhaust their quotas or hit `429 Too Many Requests`, the system gracefully degrades to the 3 provided Cloudflare Mistral-Small keys.
  3. **Fallback 2 (Groq):** As an absolute floor, it falls back to 4 provided Groq Llama-4-Scout keys if the first two lanes fail completely.
- **Result:** The backend orchestrator transparently absorbs API rate limits by catching `VLMUnavailable` exceptions and natively burning through all 15 configured API keys before ever surfacing a failure or infinite spinner to the user frontend.

---

## 3. Deterministic Typography Brittleness on Heterogeneous Layouts (Z-Score False Positives)

**Date Discovered:** 2026-07-01  
**Symptom:** 
Documents with complex but genuine layouts (e.g., IT Statements, official government forms, and multi-script IDs) are falsely flagged as tampered by the `font_layout` analyzer. The system reports 100% suspicion due to massive Z-score spikes on specific words (like "Address" or "Individual"), despite the document being a pristine, untampered original.

**Root Cause:**
- The Layer 5 Typography engine relies on strict, deterministic math. It calculates median text height, baseline, and stroke width across the document and uses standard deviations (Z-scores) to detect copy-paste insertions (a technique heavily optimized for homogeneous layouts like tabular bank statements).
- However, real-world documents (like IT Statements) frequently use different font dictionaries, bolding variations, or slightly altered baselines for headers, form field labels, or legal clauses. 
- The deterministic engine lacks semantic understanding. It misinterprets these genuine, albeit messy, stylistic choices as anomalous tampering.
- Attempting to code hardcoded exceptions for every single document type, language script, and layout variation creates an unsustainable "whack-a-mole" maintenance burden that will inevitably break on the next unseen document format.

**Resolution (Implemented) — route the typography check by medium; keep it self-referential, no black-box ML.**
- **Heterogeneity guard (already in `forensics/layout.py`):** when a large fraction of words flag, the layout is inherently mixed (ID card / multi-section form) and the Z-score is not discriminative — it returns `NOT_EVALUATED`, not a false "tampered".
- **Born-digital routes to PDF font-object forensics (Implemented, `forensics/pdf_fonts.py`).** The pixel Z-score is a category error on vector text, so a born-digital PDF (detected by a real text layer, `ctx.shared['born_digital']`) now *defers* the pixel path and runs a deterministic, **layout-agnostic, self-referential** check instead: **subset-tag inconsistency** — the same base font face appearing under more than one embedded-subset tag (`ABCDEF+Arial` **and** `GHIJKL+Arial`), which a single genuine render never emits but an editor's re-embed of an edited text run does. It needs **no corpus, no per-bank template, no threshold tuning** — the reference is the document itself. The pixel Z-score still runs on genuine *scans* (where it is the right tool). This replaces the "LayoutLM + LOF" black-box proposal with a deterministic method that stays inside Satyum's laws (rules decide, auditable).
- **Honest bound:** subset-tag consistency catches the common editor (re-embed / substitution); a skilled forger who re-embeds into the *same* subset or replaces the whole face uniformly (e.g. Sejda) defeats it — so it is graded, low-weight, orthogonal evidence, never a gate.
- **Orthogonal Defense (unchanged thesis):** typography acts with **metadata/xref forensics** (`forensics/metadata.py` — producer fingerprints, incremental-update / shadow-attack counting, impossible date order) and the **arithmetic engine**. To beat Satyum a fraudster must simultaneously beat the font objects, the hidden metadata/structure, and the financial arithmetic.

---

## 4. Arithmetic Invariant Fragility (Hidden Fees & Multi-Page Reconciliation)

**Date Discovered:** 2026-07-01  
**Symptom:** 
Genuine bank statements are rejected with 100% anomaly scores because the deterministic math engine (`Opening + Credits - Debits = Closing`) fails to balance.

**Root Cause:**
- Certain banks (e.g., ICICI, credit cards) include "hidden" rows (like reversed charges, auto-sweeps into Fixed Deposits, GST, or annual fees) that affect the final balance but are not cleanly listed in the main transaction table. 
- Strict deterministic math cannot account for invisible ledger adjustments without context. Using dynamic LLM prompting to "hunt for the missing ₹50 residual" is dangerously slow, expensive, and risks LLM hallucinations (e.g., the LLM finding a "minimum balance penalty of ₹50" and mistakenly using it to balance a forged ledger).

**Resolution (Partially Implemented) — the principle: distinguish "I can't verify this" (REVIEW) from "this is fraudulent" (REJECT); never false-reject a genuine document.**

Rather than chase per-bank fee rules (a whack-a-mole that breaks on the next unseen layout), the fix is to make the engine *abstain when unsure* and *accuse only on a positive contradiction it can prove*. Implemented in `forensics/arithmetic.py` + `forensics/ocr.py`:

- **Completeness abstain (the core fix).** `build_statement` now emits `unstructured_money_tokens` — currency-formatted figures on the page the parser could NOT place into the table (the fingerprint of a hidden fee/charge in a layout region the columns don't span). When an invariant breaks AND the extraction is incomplete, the engine returns `NOT_EVALUATED` → **REVIEW**, never a fabricated "tampered". A genuine statement with an uncaptured charge is no longer false-rejected. Conservative by design: only unambiguous money shapes count (a reference/cheque number never triggers it), so tamper detection is not weakened.
- **Failure typing.** A **running-balance** break (a printed balance that doesn't follow from its neighbours — the signature of an edited transaction figure) stays **full tamper strength**. An **aggregate-only** discrepancy (every balance chains, but a stated total/closing/net-reconciliation is off — indistinguishable from an unextracted fee) is graded into the **REVIEW band** and can never, on its own, auto-REJECT. Materiality scales it: an immaterial residual (fee-scale) leans clean-review, a material one flags harder for the human.
- **Both arithmetic paths now share the discipline.** The OCR path (`ArithmeticConsistencyAnalyzer`) AND the VLM claim-graph path (`ConsistencyRulesAnalyzer` / financial rule pack) both type failures (running-balance break = tamper; aggregate-only = REVIEW) and abstain on incomplete extraction. The VLM path reuses the OCR path's `unstructured_money_tokens` as a cross-signal, so a break coinciding with uncaptured money on the page is held pending on both.
- **Born-digital text-layer extraction (Implemented, ADR-004 Tier 2).** `forensics/ocr.text_layer_words` reads the statement straight from a born-digital PDF's TEXT LAYER (exact characters + geometry via PyMuPDF `get_text("words")`), and `DocumentParseAnalyzer` now prefers it over OCR-on-raster (`statement_source: pdf_text_layer` vs `ocr_raster`), falling back to OCR for scans/images. This makes the deterministic arithmetic path **VLM-independent and cloud-free for the common case** (survives a VLM outage — KNOWN_ISSUES #1/#2), removes OCR-misparse false-flags, and — because every monetary figure is now exact — makes the `unstructured_money_tokens` completeness signal far more reliable (a hidden fee at an exact out-of-column position is precisely detected instead of OCR-dropped).
- **Robust reconciliation (Implemented).** (a) **One-pass summary extraction** — `build_statement` now captures stated fees/charges/GST/taxes (`stated_charges`) and interest (`stated_interest`) from summary rows, and the net-reconciliation + closing-balance invariants fold them in (`opening + credits + interest − debits − charges == closing`). A genuine statement with a hidden fee now reconciles cleanly instead of tripping a false break — and because these terms never touch the per-row running chain, they cannot mask an edited-figure tamper. (b) **Multi-page "Zipper"** — `text_layer_words_per_page` + `page_boundary_pairs` read each page's stated opening/closing, and the engine checks `page[n].closing == page[n+1].opening`; a deleted page (to hide transactions) breaks the continuity and scores as a chain discontinuity (tamper), not REVIEW.
- **Honest bounds / still open:** The zipper covers born-digital multi-page PDFs (exact text layer); scanned multi-page statements still parse page-1 only. Summary-fee capture is conservative (only a labelled fee/interest row *without* a running balance), so an unlabelled adjustment still degrades to REVIEW (never a false reject).
- **We never guess missing money to balance the ledger** (the charter forbids it). An unexplained-but-plausible gap is a REVIEW for a human, never an AI-fabricated reconciliation.

---

## 5. Layer 2 Extraction Hallucinations & Deterministic Misinterpretations

**Date Discovered:** 2026-07-01  
**Symptom:** 
Perfectly genuine documents (e.g., Canara Bank statements) are rejected with multiple false-positive flags across different layers. Symptoms include the math failing on what appears to be a clean ledger, the system detecting a forged Aadhaar number on a document that isn't an Aadhaar card, and the system identifying the wrong bank (e.g., HDFC instead of Canara) and penalizing the user for not using a source-pull API.

**Root Cause:**
This is a compounding failure between Layer 2 (VLM Extraction) and Layers 4/5 (Deterministic Rules).
1. **Math Imbalance:** If a document spans multiple pages or has complex/hidden fee rows, the VLM might fail to extract every single ledger entry perfectly. The deterministic arithmetic engine downstream blindly subtracts debits from credits, and if it falls short by even a single Rupee due to the VLM's partial extraction, it asserts that the document has been tampered with.
2. **Context-Blind Regex Triggers:** Canara Bank statements often print 12-digit Customer IDs at the top of the page. The VLM dutifully extracts this 12-digit number. The downstream Entity Extraction layer blindly passes any 12-digit number to the UIDAI Verhoeff checksum algorithm. Since it's a bank account number and not an Aadhaar number, it fails the cryptomath checksum, and the deterministic layer falsely flags an "Aadhaar forgery."
3. **Issuer Hallucination:** A user's bank ledger might contain a UPI transaction line such as `UPI / HDFC BANK / XXXXX`. The VLM might incorrectly latch onto "HDFC Bank" and extract it as the document's issuer. The deterministic layer then checks HDFC against its list of "source-verifiable" banks, realizes the user submitted a flat PDF instead of using the HDFC API, and applies a severe red flag penalty.

**Resolution (Partially Implemented):**
- **Aadhaar context-gate (Implemented, fixes 5.2).** `forensics/entities.py` no longer routes *every* 12-digit number through the UIDAI Verhoeff checksum. A number is treated as an Aadhaar **only** when it carries Aadhaar context — the canonical UIDAI 4-4-4 spaced print grouping, *or* a nearby `Aadhaar`/`UID`/`VID`/`आधार` label on the same line. A bare bank Customer ID / CIF / account number therefore produces **no** `aadhaar_invalid` forgery signal. Genuine Aadhaar detection (spaced, or labelled) is preserved. Discrimination tests in `tests/test_entities.py`.
- **Issuer masthead priority (Implemented, fixes 5.3).** `verification/provenance.detect_issuer` now returns the issuer whose name appears **earliest** in the document (the masthead), not whichever registry key was checked first. A genuine Canara statement carrying an incidental `UPI/HDFC BANK/…` transaction line is correctly labelled **Canara**, not HDFC. Test in `tests/test_red_flag.py`.
- **Math imbalance from partial extraction (5.1) — mitigated (see Issue #4).** The arithmetic engine now abstains when extraction is incomplete and types the failure severity instead of asserting tampering on every break.
