/**
 * Wire contract — the EXACT JSON shape the backend publishes.
 *
 * These types mirror, field-for-field:
 *   - backend/app/contracts.py  : Mode, SignalStatus, Verdict, Provenance, LayerSignal, TrustScore
 *   - backend/risk/evidence.py  : build_evidence_pack(...) -> evidence_pack
 *
 * Keep this file in lockstep with those modules (CLAUDE.md §4 "stable, versioned contract";
 * §11 "keep frontend/backend in lockstep"). If the Python contract changes, change this first.
 *
 * NOTHING here is invented for the UI. Every field is rendered from real backend output
 * (CLAUDE.md §9 "no fabricated UI data").
 */

// app/contracts.py :: Mode
export type Mode = "FILE" | "CAMERA" | "ANY";

// app/contracts.py :: SignalStatus
export type SignalStatus = "VALID" | "NOT_EVALUATED" | "ERROR";

// app/contracts.py :: Verdict
export type Verdict = "APPROVED" | "REVIEW" | "REJECTED";

// risk/engine.py :: TrustScore.tier_reached
export type TierReached = "source-verified" | "forensic-fallback" | "in-person-capture";

// app/contracts.py :: Provenance
export interface Provenance {
  verified: boolean;
  method: string; // "PAdES" | "C2PA" | "DigiLocker" | "AA" | "none" (free-form on the wire)
  detail: string;
  tampered: boolean; // signature present but INVALID == active tampering evidence
}

// app/contracts.py :: EvidenceRegion  (bbox is x, y, w, h in analysed-image pixel space)
export type BBox = [x: number, y: number, w: number, h: number];

export interface EvidenceRegion {
  bbox: BBox;
  label: string;
  source: string; // the detector that produced this region (auditability)
}

/**
 * One row of evidence_pack.signals (the flattened, audit-facing signal projection).
 * Note: the evidence_pack signal rows DO NOT include evidence_regions/measurements —
 * see build_evidence_pack(). Regions arrive separately in tamper_evidence_regions.
 */
export interface EvidencePackSignal {
  name: string;
  layer: number;
  producing_mode: Mode;
  status: SignalStatus;
  suspicion: number | null; // null unless status === "VALID"
  weight: number;
  reason: string;
}

// risk/evidence.py :: tamper_evidence_regions[] (EvidenceRegion + the signal's suspicion)
export interface TamperEvidenceRegion extends EvidenceRegion {
  suspicion: number | null;
}

// risk/evidence.py :: pending_not_evaluated[]
export interface PendingSignal {
  name: string;
  reason: string;
}

/**
 * risk/evidence.py :: build_evidence_pack network_intelligence[] — a Layer-3 advisory FINDING, never a
 * verdict (PROPOSAL-001 §5.4/§8.4). Surfaced to the underwriter as context; it never auto-declines and
 * never entered the deterministic score. Optional on the pack until the federation backend is wired.
 */
export interface NetworkIntelligenceFinding {
  source: string; // "fraud_registry" | "ring_evidence" | "campaign_resemblance"
  suspicion: number;
  confidence: number;
  explanation: string;
  note: string; // "finding — not a verdict (advisory; never auto-declines, never clears)"
  measurements: Record<string, unknown>;
}

/**
 * risk/evidence.py :: build_evidence_pack(...) return value.
 * This is the auditable case file the underwriter acts on.
 */
export interface EvidencePack {
  session_id: string;
  document_type: string | null;
  intake_mode: Mode;
  tier_reached: TierReached;
  provenance: Provenance;
  trust_score: number;
  verdict: Verdict;
  fail_closed: boolean;
  recommended_action: string;
  reasons: string[];
  signals: EvidencePackSignal[];
  pending_not_evaluated: PendingSignal[];
  tamper_evidence_regions: TamperEvidenceRegion[];
  // Layer-3 advisory findings + the purely-deterministic sub-score. Optional: present only once the
  // federation backend (registry/ring) is wired onto main; absent responses guard with `?? []`.
  network_intelligence?: NetworkIntelligenceFinding[];
  deterministic_subscore?: number | null;
  privacy_note: string;
}

// app/contracts.py :: LayerSignal (the full signal, as carried on TrustScore.signals)
export interface LayerSignal {
  name: string;
  layer: number;
  mode: Mode;
  status: SignalStatus;
  suspicion: number | null;
  weight: number;
  reason: string;
  evidence_regions: EvidenceRegion[];
  measurements: Record<string, unknown>;
  producing_mode: Mode;
}

// ---------------------------------------------------------------------------------------------
// v2 progressive-evidence types (ADR-004) — additive, all optional on TrustScore.
// Absent in v1 responses; every component that reads these guards on `?.` / `?? []`.
// Mirrors backend/app/contracts.py v2 additions (keep in lockstep, CLAUDE.md §11).
// ---------------------------------------------------------------------------------------------

/**
 * Extraction provenance for a single Claim (ADR-004 §5 VLM trust boundary).
 * corroborating_read = what deterministic OCR independently read; null = OCR not yet run.
 * cross_read_agree: true = consensus; false = DISAGREED → claim status = "DISAGREED";
 *                   null = OCR not yet run.
 */
export interface ClaimProvenance {
  doc_id: string;
  page: number;
  bbox: BBox | null;
  confidence: number; // 0..1 VLM extraction confidence
  source: "vlm" | "ocr";
  corroborating_read: string | null;
  cross_read_agree: boolean | null;
}

/** One canonical claim in the claim graph (Layer 3, ADR-004 §3). */
export interface Claim {
  subject: string;   // e.g. "bank_statement_1"
  predicate: string; // e.g. "running_balance[row=7]"
  value: string;
  value_type: "MONEY" | "DATE" | "NAME" | "ID" | "NUMBER" | "TEXT";
  provenance: ClaimProvenance;
  /** VERIFIED = VLM + OCR agree · DISAGREED = cross-read mismatch → NOT_EVALUATED verdict */
  status: "VERIFIED" | "NOT_EVALUATED" | "DISAGREED";
}

/** Per-rule result from a deterministic rule pack (Layer 4, ADR-004 §3). */
export type RuleStatus =
  | "PASS"
  | "FAIL"
  | "UNKNOWN"
  | "NOT_APPLICABLE"
  | "NOT_EVALUATED";

export interface RuleResult {
  rule_id: string;
  description: string;
  status: RuleStatus;
  reason: string;
  claims_used: string[]; // predicate refs into the claim graph that this rule consumed
}

/** One domain's rule pack output (financial / land / legal). */
export interface RulePackResult {
  domain: "financial" | "land" | "legal";
  rules: RuleResult[];
}

/** Layer 0 — evidence sufficiency classification (what confidence the submission can achieve). */
export type EvidenceLevel = "single-document" | "case-context" | "corroborated";

export interface EvidenceSufficiency {
  level: EvidenceLevel;
  doc_count: number;
  source_types: string[]; // e.g. ["pdf", "salary_slip", "form16"]
  achievable_confidence: "LOW" | "MEDIUM" | "HIGH";
}

/**
 * One soft signal from Layer 5 anomaly intelligence (ADR-004 §3).
 * verdict_impact is always "REVIEW" — anomaly signals never harden to REJECT.
 * is_ml=true → the optional ML lane (labeled "experimental"); is_ml=false → deterministic stats.
 */
export interface AnomalySignal {
  kind: string;
  reason: string;
  verdict_impact: "REVIEW";
  is_ml: boolean;
  ml_label?: "experimental";
}

/** Status for one layer in the verification waterfall (shown in PipelineWaterfall). */
export type PipelineStepStatus = "PASS" | "FAIL" | "SKIP" | "NOT_EVALUATED" | "ERROR";

export interface LayerPipelineStatus {
  layer: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;
  name: string;
  ran: boolean;
  status: PipelineStepStatus;
  tier: 1 | 2 | 3 | null; // which verification tier this layer belongs to; null = cross-tier
}

/**
 * app/contracts.py :: TrustScore — the published verdict the bank's core consumes,
 * returned by POST /api/verify. `.evidence_pack` is the embedded EvidencePack above.
 */
export interface TrustScore {
  session_id: string;
  intake_mode: Mode;
  doc_type: string | null;
  provenance: Provenance;
  trust_score: number;
  verdict: Verdict;
  tier_reached: TierReached;
  signals: LayerSignal[];
  evidence_pack: EvidencePack;
  fail_closed: boolean;
  // v2 optional fields — absent in v1 responses; all consumers guard with `?.`
  evidence_sufficiency?: EvidenceSufficiency;
  claim_graph?: Claim[];
  rule_pack_results?: RulePackResult[];
  anomaly_signals?: AnomalySignal[];
  pipeline_layers?: LayerPipelineStatus[];
}

// ---------------------------------------------------------------------------------------------
// Bundle verification (POST /api/verify-bundle) — the cross-document consistency graph (ADR-003 #3).
// Mirrors backend/app/contracts.py :: BundleDocument, BundleTrustScore and the cross_document signal's
// measurements emitted by forensics/cross_document.py. Nothing here is invented for the UI.
// ---------------------------------------------------------------------------------------------

// app/contracts.py :: BundleDocument
export interface BundleDocument {
  label: string; // e.g. "doc1:bank_statement.png"
  trust: TrustScore;
}

// forensics/cross_document.py :: FieldComparison.status (wire values are lowercase)
export type CrossFieldStatus = "agree" | "near" | "disagree";

/** One field's cross-document comparison (forensics/cross_document.py measurements.comparisons[]). */
export interface CrossFieldComparison {
  field: string; // "pan" | "aadhaar" | "ifsc" | "account_number" | "name" | "dob"
  status: CrossFieldStatus; // AGREE · NEAR (possible OCR slip → review) · DISAGREE
  agree: boolean; // status === "AGREE" (kept for convenience; mirrors the backend)
  values: Record<string, string>; // doc label -> the value that document carries
}

/** The measurements payload carried on the cross_document LayerSignal. */
export interface CrossDocumentMeasurements {
  compared_fields?: string[];
  documents?: number;
  comparisons?: CrossFieldComparison[];
  disagreeing_fields?: string[];
  hard_mismatch_fields?: string[]; // dispositive identifier mismatches (PAN/Aadhaar/account/dob)
  near_match_fields?: string[]; // single-char OCR-slip near-matches → REVIEW, not REJECT
}

// app/contracts.py :: BundleTrustScore
export interface BundleTrustScore {
  session_id: string;
  document_count: number;
  documents: BundleDocument[];
  cross_document: LayerSignal; // measurements typed as CrossDocumentMeasurements at use sites
  bundle_score: number;
  bundle_verdict: Verdict;
  fail_closed: boolean;
  reasons: string[];
}

// ---------------------------------------------------------------------------------------------
// Live-capture (WebSocket /ws/verify) protocol — Tier-3 active 3D challenge.
// Mirrors architecture/BUILD-MANIFEST.md "Active server-randomized 3D challenge": the server
// issues an unpredictable just-in-time tilt command and verifies the tracked document motion matches
// it via homography. The frontend streams frames and renders the active-challenge instruction + live
// per-tier status. The backend route (backend/app/routes/verify.py :: verify_camera) implements
// EXACTLY this contract — they are kept field-for-field in lockstep (CLAUDE.md §11). If the route is
// unreachable, the client connects honestly and reports the real state, never fabricating challenge
// data (CLAUDE.md §3.1, §3.4).
// ---------------------------------------------------------------------------------------------

export type ChallengeKind = "tilt-left" | "tilt-right" | "tilt-up" | "tilt-down" | "rotate-cw" | "rotate-ccw" | "move-closer" | "move-away";

/** Server -> client: issue/refresh the active physical challenge. */
export interface ServerChallengeMessage {
  type: "challenge";
  challenge_id: string;
  kind: ChallengeKind;
  instruction: string; // human-readable command, e.g. "Tilt the document's left edge toward the camera"
  expires_at_ms: number; // epoch ms; the challenge nonce is time-bounded (anti-replay)
  // The authoritative command the analyzer verifies (axis + magnitude; direction in `kind` is a
  // human cue, not separately verified — see verify.py). Present on the wire; not required by the UI.
  axis?: "x" | "y";
  magnitude_deg?: number;
}

/** Server -> client: live per-tier / per-signal status as the pipeline runs on streamed frames. */
export interface ServerTierStatusMessage {
  type: "tier_status";
  signals: EvidencePackSignal[]; // same projection as the evidence pack, evaluated live
}

/** Server -> client: the final TrustScore once the live session concludes. */
export interface ServerResultMessage {
  type: "result";
  trust_score: TrustScore;
}

/** Server -> client: an honest error/notice from the backend. */
export interface ServerNoticeMessage {
  type: "notice" | "error";
  message: string;
}

export type ServerMessage =
  | ServerChallengeMessage
  | ServerTierStatusMessage
  | ServerResultMessage
  | ServerNoticeMessage;

/** Client -> server: a captured frame (downscaled JPEG, base64) + the challenge it answers. */
export interface ClientFrameMessage {
  type: "frame";
  challenge_id: string | null;
  ts_ms: number;
  jpeg_base64: string;
}

/** Client -> server: begin a live verification session. */
export interface ClientHelloMessage {
  type: "hello";
  doc_type: string | null;
}

export type ClientMessage = ClientFrameMessage | ClientHelloMessage;
