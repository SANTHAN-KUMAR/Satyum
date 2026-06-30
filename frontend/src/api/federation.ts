/**
 * Typed client + wire types for the Stage 1–3 endpoints (PROPOSAL-001):
 *   - source-pull        : POST /api/sources/{provider}/pull
 *   - shared registry    : POST /api/registry/report · /api/registry/query
 *   - ring detection     : POST /api/ring/application · /api/ring/detect · GET /api/ring/case/{id}
 *   - rule-discovery loop : POST /api/rules/mine · GET /api/rules · POST /api/rules/{id}/approve|reject
 *
 * Mirrors backend providers/contracts.py, federation/*, rules/*. Nothing is invented for the UI —
 * every field renders real backend output (CLAUDE.md §9). Same-origin fetch via apiUrl().
 */

import { ApiError, apiUrl } from "./client";

// --- source-pull (providers/contracts.py) --------------------------------------------------------

export type SignatureStatus = "VERIFIED" | "INVALID" | "ABSENT" | "NOT_VERIFIED";
export type ProvenanceMode = "SOURCE_PULL" | "SANDBOX" | "MANUAL_UPLOAD" | "LIVE_CAPTURE";
export type DocClass =
  | "financial_statement"
  | "identity"
  | "land_record"
  | "legal_deed"
  | "other";

export interface SourceResult {
  provider: string;
  doc_class: DocClass;
  signature_status: SignatureStatus;
  provenance_mode: ProvenanceMode;
  issuer: string | null;
  freshness_ts: string | null;
  gate: string | null;
  detail: string;
  measurements: Record<string, unknown>;
}

export interface SourcePullResponse {
  source_result: SourceResult;
  trust_score: unknown | null; // full TrustScore when a verified doc fed the core (typed at use site)
}

// --- registry (federation/registry.py) -----------------------------------------------------------

export interface RegistryMatch {
  label: string;
  threat_class: string;
  phash_distance: number | null;
  matched_token_kinds: string[];
  banks_seen: number;
  seen_count: number;
}

export interface RegistryQueryResponse {
  matched: boolean;
  matches: RegistryMatch[];
}

// --- ring detection (federation/graph.py) --------------------------------------------------------

export interface RingEvidence {
  members: string[];
  banks: string[];
  shared_identifiers: Record<string, number>;
  weight_sum: number;
  strength: number;
  explanation: string;
}

export interface RingDetectResponse {
  ring_count: number;
  rings: RingEvidence[];
}

export interface RingFinding {
  source: string;
  suspicion: number;
  confidence: number;
  explanation: string;
  measurements: Record<string, unknown>;
  note: string;
}

export interface RingCaseResponse {
  case_id: string;
  in_ring: boolean;
  findings: RingFinding[];
}

// --- rules (rules/*) -----------------------------------------------------------------------------

export type RuleStatus = "CANDIDATE" | "APPROVED" | "REJECTED";

export interface RuleDto {
  rule_id: string;
  predicates: string;
  predicate_list: { feature: string; op: string; value: unknown }[];
  threat_class: string;
  suspicion: number;
  support: number;
  confidence: number;
  lift: number;
  provenance: string;
  status: RuleStatus;
  approved_by: string | null;
  decided_at: string | null;
}

export interface MineResponse {
  mined: number;
  candidates: RuleDto[];
}

export interface LabeledCaseIn {
  features: Record<string, unknown>;
  is_fraud: boolean;
}

// --- low-level helpers ---------------------------------------------------------------------------

async function postForm<T>(path: string, fields: Record<string, string | undefined>, file?: File): Promise<T> {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v != null && v !== "") form.append(k, v);
  if (file) form.append("file", file, file.name);
  return send<T>(path, { method: "POST", body: form });
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  return send<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { headers: { Accept: "application/json" }, ...init });
  } catch {
    throw new ApiError("Could not reach the service. Confirm the backend is running and reachable.");
  }
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b?.detail === "string") detail = b.detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(detail ?? `Request failed (HTTP ${res.status}).`, res.status, detail);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("The service returned a non-JSON response.");
  }
}

// --- public API ----------------------------------------------------------------------------------

export function pullSource(
  provider: string,
  fields: {
    doc_class: DocClass;
    consent_id: string;
    issuer_hint?: string;
    applicant_ref?: string;
    name?: string; // applicant name (PAN name-match)
    dob?: string; // DD/MM/YYYY (PAN verification)
    share_code?: string; // Aadhaar offline e-KYC ZIP password
  },
  file?: File,
): Promise<SourcePullResponse> {
  return postForm<SourcePullResponse>(`/api/sources/${provider}/pull`, fields, file);
}

export function reportFraud(fields: {
  threat_class: string;
  label: string;
  phash_hex?: string;
  pan?: string;
  account?: string;
  bank_id?: string;
}): Promise<{ reported: boolean; registry_size: number; label: string }> {
  return postForm("/api/registry/report", fields);
}

export function queryRegistry(fields: {
  phash_hex?: string;
  pan?: string;
  account?: string;
}): Promise<RegistryQueryResponse> {
  return postForm<RegistryQueryResponse>("/api/registry/query", fields);
}

export function submitApplication(fields: {
  case_id: string;
  bank_id?: string;
  device?: string;
  payout_account?: string;
  employer?: string;
  pan?: string;
}): Promise<{ added: boolean; graph_size: number }> {
  return postForm("/api/ring/application", fields);
}

export function detectRings(): Promise<RingDetectResponse> {
  return postForm<RingDetectResponse>("/api/ring/detect", {});
}

export function ringForCase(caseId: string): Promise<RingCaseResponse> {
  return send<RingCaseResponse>(`/api/ring/case/${encodeURIComponent(caseId)}`, { method: "GET" });
}

export function mineRules(cases: LabeledCaseIn[], threatClass = "mined_pattern"): Promise<MineResponse> {
  return postJson<MineResponse>("/api/rules/mine", { cases, threat_class: threatClass });
}

export function listRules(): Promise<{ rules: RuleDto[] }> {
  return send<{ rules: RuleDto[] }>("/api/rules", { method: "GET" });
}

export function approveRule(ruleId: string, approvedBy: string): Promise<{ approved: boolean; rule: RuleDto }> {
  return postJson(`/api/rules/${encodeURIComponent(ruleId)}/approve`, { approved_by: approvedBy });
}

export function rejectRule(ruleId: string, approvedBy: string): Promise<{ rejected: boolean; rule: RuleDto }> {
  return postJson(`/api/rules/${encodeURIComponent(ruleId)}/reject`, { approved_by: approvedBy });
}
