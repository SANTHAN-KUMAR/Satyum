/**
 * Runtime validation at the network trust boundary (CLAUDE.md §4: "validate everything crossing a
 * trust boundary ... reject malformed input loudly, early"). We do not blindly trust the wire even
 * from our own backend — a malformed response must surface as an honest error, never a half-rendered
 * console with `undefined` where a verdict should be.
 *
 * Lightweight, dependency-free guards (no zod) keep the bundle small and the checks auditable.
 */

import type {
  BundleTrustScore,
  EvidencePack,
  EvidencePackSignal,
  LayerSignal,
  Mode,
  Provenance,
  ServerMessage,
  SignalStatus,
  TrustScore,
  Verdict,
} from "./types";

const MODES: ReadonlySet<string> = new Set<Mode>(["FILE", "CAMERA", "ANY"]);
const STATUSES: ReadonlySet<string> = new Set<SignalStatus>(["VALID", "NOT_EVALUATED", "ERROR"]);
const VERDICTS: ReadonlySet<string> = new Set<Verdict>(["APPROVED", "REVIEW", "REJECTED"]);

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isProvenance(v: unknown): v is Provenance {
  return (
    isObject(v) &&
    typeof v.verified === "boolean" &&
    typeof v.method === "string" &&
    typeof v.detail === "string" &&
    typeof v.tampered === "boolean"
  );
}

function isPackSignal(v: unknown): v is EvidencePackSignal {
  return (
    isObject(v) &&
    typeof v.name === "string" &&
    typeof v.layer === "number" &&
    MODES.has(v.producing_mode as string) &&
    STATUSES.has(v.status as string) &&
    (v.suspicion === null || typeof v.suspicion === "number") &&
    typeof v.weight === "number" &&
    typeof v.reason === "string"
  );
}

function isEvidencePack(v: unknown): v is EvidencePack {
  return (
    isObject(v) &&
    typeof v.session_id === "string" &&
    (v.document_type === null || typeof v.document_type === "string") &&
    MODES.has(v.intake_mode as string) &&
    typeof v.tier_reached === "string" &&
    isProvenance(v.provenance) &&
    typeof v.trust_score === "number" &&
    VERDICTS.has(v.verdict as string) &&
    typeof v.fail_closed === "boolean" &&
    typeof v.recommended_action === "string" &&
    Array.isArray(v.reasons) &&
    Array.isArray(v.signals) &&
    v.signals.every(isPackSignal) &&
    Array.isArray(v.pending_not_evaluated) &&
    Array.isArray(v.tamper_evidence_regions)
  );
}

/** Validate a POST /api/verify response into a typed TrustScore, or throw with a clear message. */
export function parseTrustScore(v: unknown): TrustScore {
  if (!isObject(v)) {
    throw new Error("Malformed verification response: expected a JSON object.");
  }
  if (!MODES.has(v.intake_mode as string)) {
    throw new Error(`Malformed verification response: invalid intake_mode "${String(v.intake_mode)}".`);
  }
  if (!VERDICTS.has(v.verdict as string)) {
    throw new Error(`Malformed verification response: invalid verdict "${String(v.verdict)}".`);
  }
  if (typeof v.trust_score !== "number") {
    throw new Error("Malformed verification response: trust_score is not a number.");
  }
  if (!isProvenance(v.provenance)) {
    throw new Error("Malformed verification response: provenance block is missing or malformed.");
  }
  if (!isEvidencePack(v.evidence_pack)) {
    throw new Error("Malformed verification response: evidence_pack is missing or malformed.");
  }
  if (!Array.isArray(v.signals)) {
    throw new Error("Malformed verification response: signals is not an array.");
  }
  return v as unknown as TrustScore;
}

/** A LayerSignal carries measurements + regions; validate the load-bearing fields, not every key. */
function isLayerSignal(v: unknown): v is LayerSignal {
  return (
    isObject(v) &&
    typeof v.name === "string" &&
    typeof v.layer === "number" &&
    MODES.has(v.producing_mode as string) &&
    STATUSES.has(v.status as string) &&
    (v.suspicion === null || typeof v.suspicion === "number") &&
    typeof v.weight === "number" &&
    typeof v.reason === "string" &&
    isObject(v.measurements)
  );
}

/**
 * Validate a POST /api/verify-bundle response into a typed BundleTrustScore, or throw clearly. Each
 * per-document `trust` is validated as a full TrustScore; the cross-document signal as a LayerSignal.
 */
export function parseBundleTrustScore(v: unknown): BundleTrustScore {
  if (!isObject(v)) {
    throw new Error("Malformed bundle response: expected a JSON object.");
  }
  if (typeof v.document_count !== "number" || !Array.isArray(v.documents)) {
    throw new Error("Malformed bundle response: documents/document_count missing.");
  }
  for (const d of v.documents) {
    if (!isObject(d) || typeof d.label !== "string") {
      throw new Error("Malformed bundle response: a document entry is missing its label.");
    }
    parseTrustScore(d.trust); // throws on a malformed per-document TrustScore
  }
  if (!isLayerSignal(v.cross_document)) {
    throw new Error("Malformed bundle response: cross_document signal is missing or malformed.");
  }
  if (typeof v.bundle_score !== "number") {
    throw new Error("Malformed bundle response: bundle_score is not a number.");
  }
  if (!VERDICTS.has(v.bundle_verdict as string)) {
    throw new Error(`Malformed bundle response: invalid bundle_verdict "${String(v.bundle_verdict)}".`);
  }
  if (typeof v.fail_closed !== "boolean" || !Array.isArray(v.reasons)) {
    throw new Error("Malformed bundle response: fail_closed/reasons missing.");
  }
  return v as unknown as BundleTrustScore;
}

/** Validate a single inbound WebSocket frame (already JSON-parsed) into a typed ServerMessage. */
export function parseServerMessage(v: unknown): ServerMessage | null {
  if (!isObject(v) || typeof v.type !== "string") return null;
  switch (v.type) {
    case "challenge":
      return typeof v.challenge_id === "string" &&
        typeof v.kind === "string" &&
        typeof v.instruction === "string" &&
        typeof v.expires_at_ms === "number"
        ? (v as unknown as ServerMessage)
        : null;
    case "armed":
      return typeof v.expires_at_ms === "number" ? (v as unknown as ServerMessage) : null;
    case "tier_status":
      return Array.isArray(v.signals) && v.signals.every(isPackSignal)
        ? (v as unknown as ServerMessage)
        : null;
    case "result":
      try {
        parseTrustScore(v.trust_score);
        return v as unknown as ServerMessage;
      } catch {
        return null;
      }
    case "notice":
    case "error":
      return typeof v.message === "string" ? (v as unknown as ServerMessage) : null;
    default:
      return null;
  }
}
