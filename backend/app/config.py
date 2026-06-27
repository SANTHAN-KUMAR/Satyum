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
        {"arithmetic_consistency", "active_challenge"}
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

    # --- PKI trust anchors (public roots shipped in-repo; never private keys) --------------
    trust_anchor_dir: str = "backend/verification/trust_anchors"

    # --- Persistence ----------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://satyum:satyum@localhost:5432/satyum"
    # Ephemeral session frames are NEVER persisted (privacy by design, §10).


settings = Settings()
