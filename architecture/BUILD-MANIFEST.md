# BUILD-MANIFEST — No-Mock Reality Audit

> The honest answer to "are we hiding inability behind honesty, and will it actually work?"
> Produced 2026-06-27 by an adversarial audit (hostile prosecutor + web-checked engineer → judge).
> Governs implementation alongside [ADR-002](ADR-002-provenance-first-verification.md) and [CLAUDE.md](../CLAUDE.md).
>
> **v2 update ([ADR-004](ADR-004-v2-progressive-evidence-architecture.md)):** the verdict and every entry below
> still hold — the crypto, arithmetic, capture, and risk components are unchanged in substance. v2 inserts an
> **understanding layer** in front of the rule packs: a **VLM** reads arbitrary layouts into a **claim graph**, so
> the arithmetic engine (and new land/legal rule packs) run on *any* document, not one hardcoded layout. The new
> v2 components — VLM extraction, claim graph, domain rule packs, hybrid anomaly — are audited inline below with
> their own cop-out guards. The OCR/arithmetic entries are **rehomed** (cross-read verifier + financial rule pack),
> not removed. The new biggest trap is **VLM hallucination-laundering** — guarded by numeric cross-read consensus.

## Verdict

Yes - the system can run with mocks approaching zero, and the user's key hypothesis is CONFIRMED by repo review and live verification of the load-bearing facts (pyHanko custom trust_roots, c2pa-python verify_cert_anchors, WebNFC NDEF-only, getUserMedia spoofability). Cryptographic signature/provenance verification IS the real no-partner source-of-truth path: DigiLocker, bank e-statements, and signed land RoR/EC all reclassify SIMULATED->BUILD_REAL via CCA-chain PAdES verification, making the simulated DigiLocker/land connectors cop-outs to delete. The only genuinely-unavoidable gating is the Account Aggregator PRODUCTION live-pull (regulatory FIU credential - but build the real sandbox + real FIP-signature verifier), NFC ePassport in the browser (physically impossible per WebNFC - build native instead), and the in-browser injection check (no sensor attestation exists - keep as low-weight, documented-bypassable, never a hard gate). None of these is a cop-out: each is a proven physics/regulatory limit with the real substitute named, and every excluded pixel-forensic/biometric item is excluded with physics/data/science/ethics proof, not effort. The remaining risk is execution: the most dangerous traps are the arithmetic engine validated on one fixture, signature checks degraded to 'a signature exists', the browser sensor-check returning an unearned PASS, and invented thresholds/weights presented as calibrated - all must be guarded with adversarial CI fixtures.

## What we were dodging — corrected to BUILD-REAL

- DigiLocker verification: the 'SIMULATED DigiLocker connector' is the single biggest cop-out. DigiLocker issued docs are CCA-chain PAdES-signed; pyHanko + pinned CCA root verifies issuer+integrity offline with no partner. Delete the mock, build the real verifier.
- Bank e-statement signature verification: same CCA-PKI pyHanko path; the 'Signature Not Verified' in Adobe is a missing root, not a missing signature. Build it real.
- Land RoR/EC: a buildable per-state signed-RoR + QR/verification-code verifier was hidden behind the genuine (and separate) national-API gap. Build the crypto/QR half for at least one state.
- Account Aggregator: build against a REAL self-serve sandbox (Setu/Finvu) + a REAL FIP-signature verifier instead of fabricating JSON; only the production live-pull is genuinely credential/regulator-gated.
- Arithmetic-consistency engine: must be validated on an adversarial test matrix (genuine passes, single-edit breaks an invariant, real OCR noise), not one happy fixture - it is the primary signal.
- PAdES/C2PA full validation: must do chain-to-anchor + ByteRange + trust-list pinning, not 'a signature exists' - else self-signed forgeries pass.
- Detectors-weighted-to-zero (copy-move, font/layout): build them to carry real weight with proper guards, or honestly drop them - not ship a detector that never decides.

## Genuinely unavoidable gates (proven limits, real substitute named — never fabricated data)

- Account Aggregator PRODUCTION live transaction-pull: requires RBI/SEBI-regulated FIU/NBFC-AA onboarding - a real regulatory credential a student team cannot obtain in the timeframe. Substitute is real (self-serve sandbox + real FIP-signature verification + signed-statement verification for the issuer+integrity question); only live data FRESHNESS has no no-partner substitute. Must be labeled partner/regulator-gated, never presented as live.
- NFC ePassport read in the BROWSER: physically impossible because WebNFC is NDEF-only by design (no ISO 7816 APDU / ISO-DEP) - verified. This is not simulated, it is excluded for the web medium with proof; the REAL working version exists as a native iOS/Android app (jMRTD / NFCPassportReader + CSCA masterlist), so even here the honest path is build-native, not simulate.
- Virtual-camera/injection integrity in a PURE WEB stack: a browser exposes no genuine-sensor attestation and getUserMedia/enumerateDevices are cloak-spoofable, so a JS-only check cannot truly discriminate injection. The real working version requires native platform attestation (Play Integrity / DeviceCheck). In-web it must be low-weight, documented-bypassable corroboration - never a justified PASS.

## Component manifest

### PAdES/eIDAS digital-signature verification on signed PDFs — `BUILD_REAL_WORKS`
- **Real approach:** pyHanko (validate_pdf_signature / validate_pdf_ltv_signature) with ValidationContext(trust_roots=[load_cert_from_pemder(...)]). Verified against docs: it hashes the /ByteRange, verifies the CMS/PKCS#7 signature math, builds the X.509 chain to the supplied trust anchor, validates embedded RFC3161 timestamps, and does CRL/OCSP revocation. No partner, fully offline. Apache PDFBox is the Java equivalent.
- **Cop-out guard (must-fail CI):** Risk: degrading to 'a signature exists' (signature.intact only) so an attacker's self-signed cert passes; ignoring /ByteRange so appended-content (incremental-update) tamper passes; hardcoding 'valid' when OCSP is offline. Guard: two adversarial fixtures that MUST FAIL CI - (a) PDF signed with attacker's own cert -> chain-to-anchor fails; (b) validly-signed PDF with bytes appended after ByteRange -> digest mismatch. Fail closed on unreachable revocation.

### C2PA / Content Credentials manifest validation — `BUILD_REAL_WORKS`
- **Real approach:** c2pa-python (contentauth SDK over c2pa-rs). Verified: Settings.from_dict({'verify':{'verify_cert_anchors':True},'trust':{'trust_anchors':anchors_pem}}) pins a trust list and enables offline cert-anchor verification; Reader checks the COSE signature, cert chain, and the hard-binding hash against file bytes.
- **Cop-out guard (must-fail CI):** Risk: validating a manifest signature WITHOUT pinning a trust list (the documented c2patool self-signed-manifest exploit passes); treating absence-of-manifest as a pass. Guard: must set verify_cert_anchors=True with a pinned anchor; absence-of-manifest renders 'no provenance (logged)', present-but-broken is a red flag, only present+valid is positive. Note: C2PA on bank statements is near-zero in the wild, so this is correctly a secondary/image path, not the primary financial-doc signal.

### Bank-issued digitally-signed e-statements (chain to bank/CA cert) — `BUILD_REAL_WORKS`
- **Real approach:** Same pyHanko path with India CCA PKI as trust anchor. Indian bank e-statements (and PAN/ITR/GST) are routinely signed by CCA-licensed CAs (eMudhra, nCode). The Adobe 'Signature Not Verified' is only a missing CCA root in Adobe's store, NOT a missing signature - install the CCA root as trust anchor and the chain verifies. Genuine no-partner cryptographic proof of issuer+integrity.
- **Cop-out guard (must-fail CI):** Risk: claiming universal coverage. Reality: not every bank signs every statement, so this is high-confidence WHEN a signature is present; absence must route to the Tier-2 forensic path, never auto-pass. Guard: explicit 'signature present?' branch; absence != pass.

### DigiLocker-issued document verification — `BUILD_REAL_WORKS`
- **Real approach:** RECLASSIFY SIMULATED -> BUILD_REAL. DigiLocker 'Issued Documents' are PDFs PAdES-signed under the CCA India PKI by NeGD. You do NOT need the DigiLocker pull API: verify the embedded CCA-chained signature offline with pyHanko + pinned CCA root (shipped in-repo). The 'yellow question mark' is a missing root, not a missing signature. Both prosecutor and engineer, plus verified pyHanko trust_roots support, confirm this.
- **Cop-out guard (must-fail CI):** This is the headline cop-out in the current plan. The 'SIMULATED DigiLocker connector' is effort-dodging dressed as the honest-stub rule - a real no-partner verifier was buildable. isMock=true reflects the CURRENT plan; the mandated end-state is the real signature verifier (isMock would become false). Guard: delete the mock connector; the only acceptable artifact is the pyHanko CCA-chain verifier with adversarial fixtures.

### Account Aggregator (RBI/Sahamati) data pull — `GATED_BUT_REAL_SUBSTITUTE`
- **Real approach:** Two real halves: (1) build against a REAL self-serve sandbox (Setu/Finvu/OneMoney give x-client-id/secret on signup, ReBIT-spec) instead of fabricated JSON; (2) the FIP returns FIP-SIGNED JSON, so build the real signature-verification half even on sandbox payloads. Production live-pull genuinely requires RBI/SEBI-regulated FIU onboarding (a real credential/regulatory blocker for a student team). The no-partner substitute for the issuer+integrity question is signature verification of the signed statement (above); AA's unique signal is data FRESHNESS, which signatures can't replace.
- **Cop-out guard (must-fail CI):** Risk: 'fully simulated AA connector' overclaims the blocker and presents fabricated JSON as live. Guard: 'simulated' must mean 'real sandbox client + real FIP-signature verifier', never fabricated data presented as live; Evidence Pack labels production pull as partner/regulator-gated with the precise reason (NBFC-AA/FIU onboarding).

### Land registry / Encumbrance Certificate cross-reference — `BUILD_REAL_PARTIAL`
- **Real approach:** BUILD_REAL for the crypto half: many state RoR/EC portals (Maharashtra Mahabhumi, UP, others under DILRMP) issue CCA-signed 'Digitally Signed Extract' / certified RoR with QR codes - verify those with pyHanko + the public verification-code/QR endpoints the portals expose. No partner. EXCLUDE only 'automated national encumbrance search': no uniform national API exists; coverage is state-fragmented and CAPTCHA-gated (infrastructure gap, not effort).
- **Cop-out guard (must-fail CI):** Risk: a blanket 'simulated land-registry connector' hides a buildable per-state signed-RoR/QR verifier behind the genuine national-API gap. Guard: build signature+QR verification for at least one state with real signed samples; label 'national automated search' EXCLUDED with the fragmentation proof, not faked.

### NFC ePassport chip read + Passive Authentication — `GATED_BUT_REAL_SUBSTITUTE`
- **Real approach:** PROVEN: WebNFC (Chrome/Android) is NDEF-only BY DESIGN - ISO 7816 APDU / ISO-DEP secure messaging is explicitly unsupported, so BAC/PACE + DG1/DG2/SOD read is technically IMPOSSIBLE in the browser (not lazy). The real, fully-working path is a NATIVE app: jMRTD (Android) / AndyQ NFCPassportReader (iOS) -> BAC/PACE -> read data groups -> Passive Authentication (SOD signed by DSC, chain to CSCA per ICAO Doc 9303, hash-match every DG). CSCA masterlist is public (ICAO PKD / German BSI).
- **Cop-out guard (must-fail CI):** Risk: vaguely 'deferred', or worse, ever claiming a browser NFC read works (that would be a fabricated signal). Guard: doc must state the precise WebNFC-NDEF-only/APDU reason; build it for real in a native capture step or defer honestly with that proof. Never a browser NFC pass.

### 'PDF-only when source-pull was possible' red-flag logic — `BUILD_REAL_WORKS`
- **Real approach:** Deterministic rule engine over a REAL capability map: a registry of which issuer/bank is source-verifiable (AA-enabled / signs statements / DigiLocker-issuable) for THIS doc; if a verifiable source existed but only an unsigned PDF was submitted, raise risk. No external dependency.
- **Cop-out guard (must-fail CI):** Risk: a return-True 'source was possible' with no real capability map = decorative flag. Guard: must consult an actual issuer-capability registry; unit-test that an AA-enabled bank + unsigned-PDF raises the flag and a non-sourceable issuer does not.

### PDF metadata/structure forensics — `BUILD_REAL_WORKS`
- **Real approach:** pikepdf / PyMuPDF / qpdf: Producer/Creator strings, mod-date vs create-date skew, incremental-update / xref generation count. Deterministic, no partner.
- **Cop-out guard (must-fail CI):** Risk: a 3-string Producer blocklist - trivially evaded and FP-prone on legit print-to-PDF (RESEARCH-001 warns of this). Guard: treat as weighted evidence (incremental-update structure, date skew) not a binary blocklist; FP-test against legitimate print-to-PDF samples.

### Template fingerprinting vs known bank templates — `BUILD_REAL_PARTIAL`
- **Real approach:** OpenCV layout/anchor matching against a self-built reference library of known templates. Real ONLY if a genuine corpus of real templates exists.
- **Cop-out guard (must-fail CI):** Risk: 'fingerprint' one Canara sample and match it against itself - a silent no-op. Guard: require a multi-template corpus (multiple banks/versions); without a real corpus this is honestly NOT_EVALUATED, not a fake pass. Scope corpus size to what's collectable in the timeframe.

### OCR field extraction — `BUILD_REAL_WORKS` (v2: now the cross-read verifier)
- **Real approach:** PaddleOCR (strong on Indian docs) or Tesseract; per-field bbox + confidence. **v2:** no longer the primary extractor — the VLM reads arbitrary layouts into the claim graph; this deterministic OCR **independently re-reads every numeric claim on its exact crop** (the cross-read consensus that stops VLM hallucination-laundering, [ADR-004 §5](ADR-004-v2-progressive-evidence-architecture.md)).
- **Cop-out guard (must-fail CI):** Risk: ignoring confidence so low-confidence fields silently flow into invariants. Guard: low-confidence field renders 'unreadable - pending', never 'tampered' and never a silent value; a VLM-vs-OCR numeric disagreement → `NOT_EVALUATED`, never a silent pick.

### Cross-field/arithmetic consistency engine (primary signal) — `BUILD_REAL_WORKS` (v2: the financial rule pack over the claim graph)
- **Real approach:** Deterministic invariants over the **claim graph** (no longer a hardcoded `StatementData` bound to one layout): balance carry-forward (prev +/- txn = new), subtotal = sum(line items), debits = credits, declared vs computed income/tax, monotonic dates, MRZ check digits, salary-slip net ≈ bank credit. Survives the camera/codec medium because it operates on READ NUMBERS, not pixels. The strongest in-document tamper signal; **rehomed** as the financial rule pack, unchanged in spirit.
- **Cop-out guard (must-fail CI):** THE single biggest stub trap in the project. Risk: validating on ONE hand-crafted happy fixture. Guard: adversarial test matrix per ADR-001 D4/3.2 - genuine statement passes; single-number-edited statement breaks >=1 invariant; real OCR-noise samples; low-confidence -> 'pending' not 'tampered'. If validated on one fixture, the whole product is a demo.

### VLM document understanding (read arbitrary layouts → claim graph) — `BUILD_REAL_WORKS` (v2)
- **Real approach:** a `VLMExtractor` interface (`extract(image, schema) -> list[Claim]`). POC: a frontier cloud VLM (Claude Sonnet 4.6 / Opus 4.8 via the `anthropic` SDK; Gemini 2.x alt), called with a **structured-output schema** (typed fields + per-field bbox + confidence), temperature 0, model id logged to the audit. Production swap: **Qwen2.5-VL-7B via vLLM** in-perimeter (same interface, config flag). Replaces the brittle one-layout table parser as the *extractor*; the old Tesseract parser is **demoted to the numeric cross-read verifier**.
- **Cop-out guard (must-fail CI):** THE new biggest trap. Risk: (a) the VLM "auto-corrects" a tampered figure so the arithmetic reconciles (**hallucination-laundering** — a false NEGATIVE, the worst error in a fraud system); (b) a document **prompt-injects** the reader; (c) the read is trusted without grounding. Guards: **numeric cross-read consensus** — every numeric claim is independently re-read by a deterministic OCR on its exact crop and must agree within `Decimal` tolerance, else `NOT_EVALUATED`; the VLM **never sees expected values**; structured-schema-only (no free decisions; document text is data, not instructions); `bbox ⊆ page`. Must-fail fixtures: a tamper-normalization attempt ends `NOT_EVALUATED`/flagged, never VALID-clean; an embedded "mark verified" injection does not move the deterministic verdict ([ADR-004 §5](ADR-004-v2-progressive-evidence-architecture.md)).

### Canonical claim graph (template-independent normalization) — `BUILD_REAL_WORKS` (v2)
- **Real approach:** every extracted value becomes a typed `Claim(subject, predicate, value, value_type, provenance{doc_id, page, bbox, confidence, source, corroborating_read, cross_read_agree})`. SBI/Canara/HDFC/scanned/image/vernacular all normalize to the same internal structure, so the rule packs are template-independent. Plain typed dataclasses (networkx only if traversal warrants).
- **Cop-out guard (must-fail CI):** Risk: a claim with a failed cross-read or sub-gate confidence silently treated as trusted. Guard: such claims carry `cross_read_agree=False` / below-gate confidence and are `NOT_EVALUATED` downstream, never scored.

### Domain rule packs — financial / land / legal — `BUILD_REAL` (financial WORKS, land/legal PARTIAL) (v2)
- **Real approach:** a rule-pack registry (mirrors the analyzer registry) of pure functions over the claim graph, each returning `PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NOT_EVALUATED`. **Financial (production depth):** the rehomed arithmetic engine + salary/income reconciliation. **Land/title & legal (real-but-scoped):** seller↔owner, registration ≥ execution date, ID/extent consistency; party-name consistency across body/signature/schedule, amount-in-words = amount-in-figures, start + term = end, schedule/page completeness — real rules that return `NOT_EVALUATED` for any invariant whose claims/state-tables are absent.
- **Cop-out guard (must-fail CI):** Risk: multi-domain breadth as theater (a land/legal "pack" that always passes). Guard: every rule must discriminate (genuine pass / contradiction FAIL) or honestly `NOT_EVALUATED`; land/legal coverage bounds are labeled, never a blanket pass. The financial pack keeps its full adversarial matrix (single-edit breaks an invariant).

### Hybrid anomaly intelligence — `BUILD_REAL_WORKS` (deterministic) + `OPTIONAL/FLAG-GATED` (ML lane) (v2)
- **Real approach:** an `AnomalyDetector` interface. **Deterministic backbone (default, always-on, auditable):** round-number synthetic credits, sudden salary jump, short/cherry-picked window, dormant-account revival, declared-vs-reference gap — NumPy/pandas statistics. **Optional ML lane (flag-gated, off in POC):** a time-series/embedding model behind the same interface, additive only.
- **Cop-out guard (must-fail CI):** Risk: an anomaly score that gates a verdict, or the ML lane presented as dispositive. Guard: anomaly is **REVIEW-only** (never approve, never reject, never a gate); no-anomaly ≠ genuine; insufficient history → `NOT_EVALUATED`; the ML lane's contribution is separable and labeled experimental, and removing it must not change any APPROVE/REJECT (only REVIEW routing).

### Font/layout/alignment anomaly — `BUILD_REAL_WORKS`
- **Real approach:** PyMuPDF embedded-font + per-glyph geometry outliers (baseline, stroke-width, x-height, kerning); surfaced as evidence-with-confidence, not a binary gate.
- **Cop-out guard (must-fail CI):** Risk: FP-heavy, so quietly weighted to ~0 = stub-by-weighting (same failure mode as copy-move). Guard: keep as a real contributing vote with a non-trivial weight justified by measured FP rate, or honestly drop it - not weight-to-zero theater.

### Spatial copy-move (ORB+RANSAC) — `BUILD_REAL_WORKS`
- **Real approach:** OpenCV ORB keypoints + RANSAC matched-offset clustering with guards against legitimately repeated structure (gridlines, logos, identical glyphs).
- **Cop-out guard (must-fail CI):** Risk: no repetition guards -> flags every gridline/logo -> down-weighted to ~0 to suppress noise = a detector that never decides. Guard: implement repetition guards so it can carry real weight; test it fires on an actual region-clone and stays quiet on legit repeated structure.

### pHash resubmission DB — `BUILD_REAL_WORKS`
- **Real approach:** imagehash perceptual hash of the rectified crop vs a fraud-hash store; Hamming threshold from an ACTUAL computed ROC.
- **Cop-out guard (must-fail CI):** Risk: a 'validated ROC threshold' that is actually a guessed Hamming constant (violates the §5 'no magic numbers' rule). Guard: compute and commit the ROC; threshold must be traceable to it.

### Document boundary detect + perspective rectify + quality gate — `BUILD_REAL_WORKS`
- **Real approach:** OpenCV contour/Hough boundary detect -> getPerspectiveTransform rectify -> blur/lighting/resolution gate that fail-closes to REVIEW on poor capture. Foundation for all camera signals.
- **Cop-out guard (must-fail CI):** Low risk. Guard: poor capture must fail-closed to REVIEW, not pass.

### Active server-randomized 3D challenge (corner-track + homography) — `BUILD_REAL_WORKS`
- **Real approach:** Track 4 document corners, fit per-frame homography; server issues an unpredictable just-in-time tilt/rotate/proximity command and verifies the tracked motion matches it. Established planar-pose technique; defeats pre-recording and exposes photo-of-screen (bezel/double-perspective breaks single-homography consistency). The legitimate, discriminating centerpiece.
- **Cop-out guard (must-fail CI):** Risk: the randomized command is issued but never actually checked against tracked corners ('tilt left' accepts any motion). Guard: discrimination test - photo-of-screen replay FAILS; live tilt matching the command PASSES; wrong-direction motion FAILS.

### Anti-spoof votes: moire FFT, specular/glare, temporal entropy — `BUILD_REAL_WORKS`
- **Real approach:** NumPy FFT moire/recapture detection, specular-reflection analysis, temporal frame-entropy for anti-replay. Each individually beatable/confoundable (halftone-printed genuine docs and banknotes produce periodic FFT peaks) -> robust ONLY as weighted ensemble votes, never standalone gates - which matches the design.
- **Cop-out guard (must-fail CI):** Risk: returning a suspiciously clean pass/fail as if dispositive. Guard: keep strictly as low/medium-weight votes; never a hard gate; document confoundability in the Evidence Pack.

### Virtual-camera / sensor-integrity (injection) check — `GATED_BUT_REAL_SUBSTITUTE`
- **Real approach:** VERIFIED mis-classification risk: in a browser, getUserMedia/enumerateDevices labels are transparently interceptable and cloaked to pass toString fingerprinting (camspoof/OBS-rename), and there is NO in-browser genuine-sensor attestation - so a pure-JS check CANNOT truly discriminate injection. The REAL working version needs platform attestation: Android Play Integrity / hardware-backed key attestation, iOS DeviceCheck/App Attest, plus frame-timing/entropy and known virtual-cam signatures - i.e. a native app. Injection is a real, industry-named threat class (ISO 30107-3 excludes it).
- **Cop-out guard (must-fail CI):** Risk: the textbook checkSensor(){return {status:'PASS'}} - a fabricated signal by the project's own §3.1, and internally contradictory (ADRs admit 'camera stops presentation, not injection' yet list this BUILD_REAL). Guard: in the web stack, this is LOW-WEIGHT corroboration, documented-bypassable, NEVER a hard gate and never a justified PASS it can't earn; the genuinely-strong version is gated behind native platform attestation. Do not oversell.

### Risk engine (weighted, fail-closed) — `BUILD_REAL_WORKS`
- **Real approach:** Deterministic weighted aggregation that degrades toward REVIEW/REJECT on any layer failure or uncertainty; weights with documented provenance.
- **Cop-out guard (must-fail CI):** Risk: 'fail-closed' claimed but an exception path quietly returns a neutral/pass score; weights as invented magic numbers (violates §5). Guard: kill-a-layer test - verdict must degrade to REVIEW, never APPROVE; every weight traceable, no bare constants.

### Underwriter Evidence Pack + deterministic tamper-evidence map — `BUILD_REAL_WORKS`
- **Real approach:** Composited ONLY from real detector outputs (OCR field anomalies, copy-move clusters, signature-chain results, hashes, OCR reconciliations) - explicitly NOT neural GradCAM. Surfaces the verification tier reached, per-signal status+mode, the D3 red-flag, and a recommended action.
- **Cop-out guard (must-fail CI):** Risk: a placeholder/decorative heatmap 'to look good for the demo' (ADR D6 forbids exactly this). Guard: every highlighted region must trace to a real measurement; assert provenance of each map region in tests.

### ELA / steganalysis (LSB/DCT) / JPEG-domain copy-move / AI-gen frequency / neural GradCAM (on camera frames) — `EXCLUDE_PHYSICALLY_IMPOSSIBLE`
- **Real approach:** PROVEN physics: video codec (VP8/VP9/H.264) deblocking + Bayer demosaic destroy the bit-level artifacts (JPEG quantization history, LSB planes, 8x8 grids, GAN frequency fingerprints) these need. ELA ~chance even on files (Hany Farid; Warif et al. IEEE); TruFor collapses 0.96->0.751 on AI forgeries; GradCAM needs a classifier validated on this exact webcam+codec distribution which does not exist. Correctly excluded on camera frames; structure/metadata forensics kept on the file path.
- **Cop-out guard (must-fail CI):** Not a dodge - excluded with physics proof. Guard against the inverse error: do NOT resurrect them on camera frames where they produce confident codec-driven output that doesn't change with tampering (a fake signal).

### PRNU / noise-residual (sensor fingerprint) — `EXCLUDE_PHYSICALLY_IMPOSSIBLE`
- **Real approach:** PROVEN data/relevance blocker: PRNU needs ~tens of reference images from the SAME physical camera to build a fingerprint - that prerequisite structurally does not exist in a one-shot doc-upload flow, and it is unreliable in saturated/text regions. Not effort.
- **Cop-out guard (must-fail CI):** Genuine exclude; the missing reference-image set is a structural data absence, not laziness.

### Micro-tremor anti-replay — `EXCLUDE_PHYSICALLY_IMPOSSIBLE`
- **Real approach:** PROVEN: the 8-12 Hz tremor lives in the human hand; a hand HOLDING a phone/screen reproduces the same tremor, so it cannot discriminate live-paper from held-screen. Correctly cut.
- **Cop-out guard (must-fail CI):** Genuine physics exclude; the active 3D challenge replaces its intended role and survives the held-phone attack.

### Hologram retroreflection / microprinting — `EXCLUDE_PHYSICALLY_IMPOSSIBLE`
- **Real approach:** PROVEN: a passive webcam cannot excite an OVD/hologram (needs controlled/retroreflective illumination); microprint is below consumer-sensor resolving power (needs >~2400dpi). Physically impossible in the web/app capture medium.
- **Cop-out guard (must-fail CI):** Genuine medium/physics exclude.

### Micro-expression / AU deception detection — `EXCLUDE_ETHICS_OR_IRRELEVANT`
- **Real approach:** PROVEN on two grounds: science (Ekman METT refuted; nonverbal deception cues ~chance, ~54%) so it does not discriminate even with unlimited data; and ethics/law (EU AI Act / GDPR / DPDP restrict emotion/deception inference, and it's biased and off-theme for KYC).
- **Cop-out guard (must-fail CI):** Genuine science+ethics exclude, correctly cut entirely (not relabeled).

### rPPG pulse + deepfake detection (face-KYC) — `GATED_BUT_REAL_SUBSTITUTE`
- **Real approach:** Quarantined to a SEPARATE consented face-KYC mode and NEVER fed into the document trust score - correct, because they cannot change with document tampering, so scoring them into the document verdict would be a fabricated signal. rPPG/deepfake are real but environment/cross-domain-fragile, so NOT_EVALUATED until validated on the real capture distribution, under DPDP consent.
- **Cop-out guard (must-fail CI):** Risk: leaking these into the document score for a flashier demo. Guard: structural separation; they never contribute to the document verdict.

