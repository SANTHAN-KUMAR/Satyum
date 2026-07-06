"""Central configuration: verdict thresholds, scoring weights, and detector tunables.

Every number here is a NAMED constant with provenance (CLAUDE.md §5 — "no magic numbers").
Thresholds that have not yet been calibrated against a real corpus are marked
``# DEFAULT — needs calibration`` and must NOT be presented as validated. Environment overrides
come from a gitignored ``.env`` via pydantic-settings.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SATYUM_", env_file=".env", extra="ignore")

    # --- Verdict thresholds (trust_score 0..100) -------------------------------------------
    # Provenance: ADR-002 verdict bands; chosen to bias toward human REVIEW (fail-safe banking).
    approve_at: float = 85.0
    review_at: float = 60.0  # [review_at, approve_at) -> REVIEW; below -> REJECTED

    # Signals that constitute substantive evidence the document's CONTENT was actually assessed
    # (ADR-002/003). On the forensic path, APPROVED requires at least one of these to have evaluated:
    # a clean *wrapper* (PDF structure, perceptual-hash resubmission) with the content unread is
    # indeterminate, not trustworthy -> REVIEW (§4, the cardinal fail-closed rule). Provenance-verified
    # documents short-circuit before this gate. arithmetic_consistency = the primary in-document tamper
    # signal (file); active_challenge = the primary liveness anchor (camera).
    substantive_content_signals: frozenset[str] = frozenset(
        {
            "arithmetic_consistency",  # legacy StatementData path (no VLM)
            "financial_consistency",  # Layer-4 claim-graph rule pack (ADR-004 §4)
            "active_challenge",
        }
    )

    # Layer-6 cross-source corroboration signals (ADR-004 §7 #2): a VALID, AGREEING one of these is what
    # lets a forensic-path document be APPROVED (clean in-document rules alone are necessary but not
    # sufficient — a recomputed reprint passes them). Cross-document IDENTITY agreement and cross-source
    # claim-graph agreement (income/employer) both count. Note: corroboration is NOT itself substantive
    # in-document content — identity agreeing across a bundle is not evidence the figures are genuine —
    # so these names are deliberately absent from substantive_content_signals above.
    corroboration_signals: frozenset[str] = frozenset(
        {
            "cross_document_consistency",  # bundle identity agreement (Layer-6 entities graph)
            "cross_source_corroboration",  # bundle claim-graph agreement (income/employer bridge)
        }
    )
    # A corroboration signal only *supports* an APPROVE when it actually AGREES — i.e. its suspicion is
    # at/below this near-zero ceiling. A disagreeing corroboration signal is VALID too (it carries the
    # mismatch), but it must pull the verdict DOWN, never prop an APPROVE up. DEFAULT — agreement is
    # emitted at ~0.04–0.05 suspicion; disagreement at >= soft (0.45), so this cleanly separates them.
    corroboration_agreement_max: float = 0.10

    # --- Per-layer scoring weights (relative; the engine normalises) -----------------------
    # Provenance: ADR-002 — the consistency engine is the primary in-document tamper signal,
    # so it carries the most weight among Tier-2 forensics. DEFAULT — needs calibration on a corpus.
    weight_arithmetic_consistency: float = 0.40
    weight_metadata_structure: float = 0.15
    weight_template_fingerprint: float = 0.10
    weight_font_layout: float = 0.10
    weight_copy_move: float = 0.10
    weight_phash_resubmission: float = 0.15
    # Cross-document consistency graph (ADR-003 #3) — bundle-level; identity agreement across the
    # statement/ID/deed. A strong signal when it fires. DEFAULT — calibrate on a real bundle corpus.
    weight_cross_document: float = 0.50
    # Cross-source corroboration bridge (ADR-004 §6 / financial.json X_INCOME) — bundle-level; the
    # claim-graph income/employer agreement across statement ↔ salary-slip ↔ Form-16/ITR. A figure-level
    # corroboration (vs identity-level cross_document). DEFAULT — calibrate on a real bundle corpus.
    weight_cross_source_income: float = 0.40
    # Income bridge tunables. Monthly take-home figures (bank salary credit vs slip net pay) are the
    # same quantity and should match within this relative tolerance (allowances/variable pay vary a
    # little month to month). DEFAULT — needs calibration on a labelled bundle corpus.
    income_rel_tolerance: float = 0.12
    # Annualised take-home must not EXCEED annual gross income (you cannot take home more than you gross)
    # beyond this slack — a hard logical floor, not a soft heuristic. DEFAULT — slack for OCR/rounding.
    income_annual_slack: float = 0.12
    # Employer name (salary slip vs Form-16/ITR) fuzzy-agreement floor. DEFAULT — OrgName match ratio.
    income_employer_min_ratio: float = 0.85
    # ID checksum (single-doc): an Aadhaar-format number that FAILS the UIDAI Verhoeff checksum is a
    # forged number OR an OCR misread. We cannot distinguish the two on one number, so it lands in the
    # REVIEW band (suspicion at the review ceiling) — a human checks, never an auto-reject. DEFAULT.
    weight_id_checksum: float = 0.35
    aadhaar_checksum_fail_suspicion: float = 0.40
    # Tier-3 capture votes (anti-spoof) — contributing votes, never hard gates (ADR-001/002)
    weight_antispoof_spectral: float = 0.15
    weight_antispoof_specular: float = 0.10
    weight_antispoof_temporal: float = 0.15
    weight_active_challenge: float = 0.50  # the centerpiece anti-replay anchor
    weight_behavioral_jerk: float = 0.10

    # --- Detector tunables (all DEFAULT — needs calibration unless noted) ------------------
    arithmetic_abs_tolerance: float = 1.0  # rupees; rounding tolerance for invariant checks
    # A running-balance break whose PRINTED figure is this far below the statement's monetary scale is a
    # likely OCR/text-layer MISPARSE (a truncated/garbage cell like "1" amid ₹2-lakh balances), not a
    # tamper: a real single-field edit substitutes a *plausible* figure of similar magnitude. When a
    # break looks like a misparse the deterministic arithmetic returns NOT_EVALUATED (pending → REVIEW),
    # never a confident "tampered" — extraction wasn't reliable enough to judge (CLAUDE.md §3.1/§4). The
    # VLM claim-graph path (cross-read-verified) remains the authoritative arithmetic when available.
    # DEFAULT — conservative (0.5%): only obvious garbage is excused; plausible edits still flag.
    arithmetic_misparse_ratio: float = 0.005
    ocr_min_confidence: float = 0.45  # below this a field is "unreadable -> pending", not "tampered"
    phash_hamming_threshold: int = 8  # 256-bit hash; <= match. DEFAULT — set from ROC on real corpus
    quality_min_laplacian_var: float = 100.0  # focus gate; below -> REVIEW (fail-closed)
    challenge_homography_tol_deg: float = 8.0  # commanded vs realised tilt tolerance
    # Tier-1 "PDF-only when a verifiable source existed" red flag (ADR-002 D3). DEFAULT — calibrate.
    red_flag_pdf_only_suspicion: float = 0.55
    red_flag_pdf_only_weight: float = 0.10

    # --- File ingestion safety (CLAUDE.md §10) --------------------------------------------
    max_file_bytes: int = 25 * 1024 * 1024  # 25 MiB upload cap

    # --- CORS (split-origin deploy: e.g. a Vercel frontend calling a Railway backend) -------
    # Comma-separated allowed origins (exact, scheme+host[:port]). Empty -> no cross-origin allowed
    # (same-origin only — correct when the frontend is served behind the same host or proxies /api).
    # Set SATYUM_CORS_ALLOW_ORIGINS="https://your-app.vercel.app" for a split deploy.
    cors_allow_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """The parsed, de-whitespaced allow-list (empty when no cross-origin access is configured)."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    # --- PKI trust anchors (public roots shipped in-repo; never private keys) --------------
    trust_anchor_dir: str = "backend/verification/trust_anchors"

    # --- Tier-1 signature revocation + timestamp policy (CLAUDE.md §10) --------------------
    # Revocation (CRL/OCSP): production sets allow_fetching=True to pull revocation info from the
    # certificate's own CRL/OCSP endpoints; offline / air-gapped deployments instead pin CRLs in
    # ``<trust_anchor_dir>/crls`` (e.g. the CCA-India CRL published next to the root). revocation_mode
    # is the certvalidator policy: "soft-fail" (tolerate *missing* revinfo, still fail a revoked cert),
    # "hard-fail" (any missing/unreachable revinfo fails — the strict banking posture), or "require".
    signature_allow_fetching: bool = False
    signature_revocation_mode: str = "soft-fail"

    # --- Layer 3 Collective Intelligence (federation) + source providers (PROPOSAL-001) ----
    # Advisory: the suspicion at/above which a registry/ring finding raises an otherwise-APPROVED
    # case to human REVIEW. Advisory NEVER lowers suspicion, NEVER clears a doc, NEVER enters the
    # deterministic score — it can only raise APPROVED -> REVIEW. DEFAULT — needs calibration.
    advisory_review_threshold: float = 0.5
    # Claimed-vs-document PAN cross-check (onboarding): a typed PAN that does not match the document's
    # PAN is a real identity-mismatch signal. DEFAULT — calibrate alongside the cross-document weights.
    weight_claimed_identity: float = 0.40
    # Promoted (analyst-approved, FL-discovered) deterministic rule over engineered features (§6.3.1).
    weight_promoted_rule: float = 0.30
    # Consortium federation secrets: salt de-correlates stored pHashes; pepper makes HMAC entity tokens
    # non-invertible (federation/tokens.py). SECRETS — in prod from a KMS/HSM, NEVER committed (§7.2/§10).
    # DEV defaults let the registry RUN locally/in tests; all-zero salt = pHash de-correlation OFF.
    federation_consortium_salt_hex: str = "00" * 32  # DEV DEFAULT — override in prod
    federation_entity_pepper: str = "satyum-dev-pepper-CHANGE-ME"  # DEV DEFAULT — override via env/KMS
    federation_bank_id: str = "satyum-local"  # this bank's stable consortium id
    # Source-of-truth PAN provider (real Income-Tax existence check via a KYC aggregator). No key →
    # the provider validates structure only and gates live existence to NOT_VERIFIED (honest, never faked).
    pan_api_base_url: str = "https://api.sandbox.co.in"
    pan_api_key: str = ""        # SATYUM_PAN_API_KEY   (secret — from the provider console)
    pan_api_secret: str = ""     # SATYUM_PAN_API_SECRET (secret)
    pan_api_version: str = "1.0.0"
    pan_api_timeout_s: float = 20.0
    pan_api_reason: str = "Loan underwriting KYC verification for a bank customer onboarding"
    # Pinned UIDAI public signing cert(s) for Aadhaar offline e-KYC XML verification (public certs only).
    # Empty -> the Aadhaar provider validates the embedded UIDAI cert against the CCA roots in the
    # configured trust_anchor_dir.
    uidai_cert_dir: str = "backend/verification/uidai_certs"

    # --- Layer 2: VLM document understanding (ADR-004 §2/§5/§7) ----------------------------
    # The model READS arbitrary layouts into a claim graph; the deterministic layers DECIDE. The
    # reader is swappable by config — no key ⇒ the analyzer gates to NOT_EVALUATED (never a fake pass).
    # Default reader (POC cloud): "anthropic" (Claude) or "gemini"; "none" disables Layer 2.
    vlm_provider: str = "anthropic"
    vlm_model: str = "claude-sonnet-4-6"  # provider-native model id; "" → the provider's default
    vlm_api_key: str = ""  # SATYUM_VLM_API_KEY — the default reader's credential
    # OpenAI-compatible backends (provider "cloudflare" / "openrouter" / "together" / "ollama" / …) —
    # one extractor, any host (forensics/extraction/openai_compatible_extractor.py). For "cloudflare"
    # set the account id below; for the generic ones set the full /v1 base URL.
    vlm_cloudflare_account_id: str = ""  # SATYUM_VLM_CLOUDFLARE_ACCOUNT_ID (Workers AI account id)
    vlm_base_url: str = ""               # SATYUM_VLM_BASE_URL e.g. https://openrouter.ai/api/v1
    vlm_max_tokens: int = 8192  # room for a dense transaction page's structured JSON (bbox+conf per cell)
    vlm_timeout_seconds: float = 60.0
    # --- Interpretability layer: the narrator + underwriter copilot (the "MCP" insight layer) -------
    # This LLM only TRANSLATES the immutable evidence pack into plain English / answers questions over
    # it — it can never change a verdict (interpretability/firewall.py). It is a TEXT model and is
    # decoupled from the vision reader on purpose: a text-only SOTA reasoner (e.g. DeepSeek v4) can
    # narrate while a separate vision model reads. Unset ⇒ falls back to the vlm_* reader credential, so
    # nothing breaks if you don't configure a dedicated interpreter. Configured via SATYUM_INTERPRET_*.
    interpret_provider: str = ""  # e.g. "deepseek" | "groq" | "gemini"; "" → reuse the vlm_* reader
    interpret_model: str = ""     # e.g. "deepseek-v4-pro"; "" → reuse vlm_model
    interpret_api_key: str = ""   # "" → reuse vlm_api_key
    interpret_base_url: str = ""  # "" → derived from interpret_provider (or reuse vlm_base_url)
    interpret_max_tokens: int = 1200  # headroom for a 3-paragraph narrative; reasoning models need room
    # A statement's rows span continuation pages; the running-balance chain and net reconciliation are
    # only correct over the COMPLETE set, so Layer 2 reads every page (ADR-004 §3). Bounded so a
    # pathological many-page upload cannot exhaust the VLM budget (one extraction call per page).
    vlm_max_pages: int = 8
    # Fallback reader (ADR-004 §7 resilience / CLAUDE.md §4 graceful degradation): when the primary
    # reader is unavailable (quota/auth) or errors on a page, the Layer-2 analyzer transparently retries
    # with this reader before failing closed. Removes the single-cloud-VLM point of failure. "groq"
    # works today — factory.py defaults its model to "qwen/qwen3.6-27b" (Groq deprecated
    # meta-llama/llama-4-scout-17b-16e-instruct for free/developer-tier use on 2026-06-17 in favor of
    # this model and openai/gpt-oss-120b; set SATYUM_VLM_FALLBACK_MODEL explicitly only to override).
    # "" → no fallback. Configured via SATYUM_VLM_FALLBACK_*.
    # NOTE: ALL `vlm_api_key` fields support comma-separated strings for automatic multi-key failover.
    vlm_fallback_provider: str = ""
    vlm_fallback_model: str = ""
    vlm_fallback_api_key: str = ""
    # Second fallback reader (Tertiary lane): when both primary and fallback 1 are exhausted.
    vlm_fallback2_provider: str = ""
    vlm_fallback2_model: str = ""
    vlm_fallback2_api_key: str = ""
    # Indic specialist for vernacular routing (ADR-004 §7; India-first). "gemini" works today; "sarvam"
    # is the sovereign Indic specialist, recognised but client-pending (see extraction/factory.py).
    vlm_indic_provider: str = ""  # "" → no specialist; the default reader handles every script
    vlm_indic_model: str = ""
    vlm_indic_api_key: str = ""
    # Content-addressed replay cache (forensics/extraction/cache.py; CLAUDE.md §4/§7). Memoizes the one
    # network-dependent step — the VLM read — keyed by the rendered page bytes, so an identical page is
    # transcribed by the reader once and thereafter replayed offline (the deterministic cross-read still
    # re-verifies every box live). Stores only genuine model output, records the original model_id, and
    # logs a hit as a replay — never a fabricated pass (§3.1). Delete the cache dir to force a fresh read.
    #   "off"     — no caching; every read is live (production default; semantics unchanged).
    #   "curated" — a live read is staged; the read path replays ONLY entries the operator explicitly
    #               saved via /api/vlm-cache (run → review → keep the good ones → replay on re-upload).
    #   "auto"    — memoize every read straight to the saved tier (no human in the loop).
    # Set via SATYUM_VLM_CACHE_MODE (e.g. "curated" for a pre-warmed demo that must survive a
    # rate-limited/offline API).
    vlm_cache_mode: str = "off"
    vlm_cache_dir: str = ".vlm_cache"  # SATYUM_VLM_CACHE_DIR — relative to the backend working dir
    # Claim-confidence gate: a cross-read-critical claim below this (or whose cross-read disagreed) is
    # carried as pending, never trusted by a rule (ADR-004 §5.2). DEFAULT — needs calibration.
    vlm_min_confidence: float = 0.55
    # Router escalation: a vernacular page the default reader read below this mean confidence is
    # re-extracted by the Indic specialist when one is configured. DEFAULT — needs calibration.
    vlm_escalate_below_confidence: float = 0.60

    # --- Layer 5: anomaly intelligence (hybrid, REVIEW-only) (ADR-004 §Layer-5) -----------
    # Soft signals only — suspicion is capped at the ontology review_only band; a triggered anomaly
    # nudges toward REVIEW, never REJECT (the hard guarantee is a Layer-7 guard). All DEFAULT — needs
    # calibration on a labeled corpus (CLAUDE.md §5).
    weight_anomaly: float = 0.10  # low weight: anomalies are supporting/soft, never a standalone gate
    anomaly_round_base: int = 5000  # a salary credit that is an exact multiple of this reads as synthetic
    anomaly_round_fraction_threshold: float = 0.60  # fire if >= this fraction of salary credits are round
    anomaly_min_salary_credits: int = 3  # need at least this many salary credits to assess roundness
    anomaly_salary_jump_ratio: float = 2.0  # month-over-month salary change beyond this ratio is a jump
    anomaly_short_window_days: int = (
        60  # statement window shorter than this is "cherry-picked" (financial.json A_FIN_3)
    )
    # Optional ML anomaly lane (additive, REVIEW-only, excluded from the determinism guarantee). Off by
    # default in the POC; no fabricated model is shipped (ADR-004 §Layer-5 / ADR-005). A real learned
    # detector registers behind the AnomalyDetector interface when this is enabled.
    anomaly_ml_enabled: bool = False

    # --- Persistence ----------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://satyum:satyum@localhost:5432/satyum"
    # Opt-in durable audit ledger (Postgres). Default False -> in-memory (tests/local). Set
    # SATYUM_DATABASE_ENABLED=true in a deploy with a reachable database_url to make the tamper-evident
    # audit chain survive restarts (§10/§11). Ephemeral session FRAMES are NEVER persisted (§10).
    database_enabled: bool = False


settings = Settings()
