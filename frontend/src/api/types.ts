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
// issues an unpredictable just-in-time tilt/rotate/proximity command and verifies the tracked
// document motion matches it via per-frame homography. The frontend streams frames and renders
// the active-challenge instruction + live per-tier status. Until the backend /ws/verify route
// exists, the client connects honestly and reports the real connection state — it never fabricates
// challenge data (CLAUDE.md §3.1, §3.4).
// ---------------------------------------------------------------------------------------------

export type ChallengeKind = "tilt-left" | "tilt-right" | "tilt-up" | "tilt-down" | "rotate-cw" | "rotate-ccw" | "move-closer" | "move-away";

/** Server -> client: issue/refresh the active physical challenge. */
export interface ServerChallengeMessage {
  type: "challenge";
  challenge_id: string;
  kind: ChallengeKind;
  instruction: string; // human-readable command, e.g. "Tilt the document to the left"
  expires_at_ms: number; // epoch ms; the challenge nonce is time-bounded (anti-replay)
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
