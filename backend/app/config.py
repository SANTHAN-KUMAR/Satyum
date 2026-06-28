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
        {"arithmetic_consistency", "active_challenge", "cross_document_consistency"}
    )

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

    # --- Persistence ----------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://satyum:satyum@localhost:5432/satyum"
    # Opt-in durable audit ledger (Postgres). Default False -> in-memory (tests/local). Set
    # SATYUM_DATABASE_ENABLED=true in a deploy with a reachable database_url to make the tamper-evident
    # audit chain survive restarts (§10/§11). Ephemeral session FRAMES are NEVER persisted (§10).
    database_enabled: bool = False


settings = Settings()
