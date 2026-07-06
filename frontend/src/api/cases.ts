import { apiUrl, ApiError } from "./client";
import type { CrossFieldComparison, EvidencePack } from "./types";

/**
 * Application-case API (backend app/routes/cases.py). A case accumulates an applicant's documents so
 * the cross-document identity corroboration strengthens as each new document is added. Documents accrue
 * via verifyDocument({ caseId }); this client creates and reads back cases.
 */

export interface CaseDocumentView {
  doc_id: string;
  label: string;
  verdict: string;
  added_at: string;
  identity: Record<string, string>; // comparable identity fields extracted from the document
}

export interface CaseView {
  case_id: string;
  applicant_ref: string | null;
  created_at: string;
  document_count: number;
  documents: CaseDocumentView[];
  corroboration_status: string; // NOT_EVALUATED | VALID
  corroboration_reason: string;
  corroboration_suspicion: number | null;
  identity_consistent: boolean;
  hard_mismatch_fields: string[];
  // Full per-field breakdown incl. the "near" OCR-slip tier — backend/app/routes/cases.py::FieldComparisonView.
  comparisons: CrossFieldComparison[];
}

async function readOrThrow(res: Response, what: string): Promise<CaseView> {
  if (!res.ok) throw new ApiError(`${what} (HTTP ${res.status})`, res.status);
  return (await res.json()) as CaseView;
}

export async function createCase(applicantRef?: string): Promise<CaseView> {
  const form = new FormData();
  if (applicantRef) form.append("applicant_ref", applicantRef);
  form.append("consent_id", `c-${crypto.randomUUID().slice(0, 8)}`);
  const res = await fetch(apiUrl("/api/cases"), { method: "POST", body: form });
  return readOrThrow(res, "Could not open the application case");
}

export async function getCase(caseId: string): Promise<CaseView> {
  const res = await fetch(apiUrl(`/api/cases/${encodeURIComponent(caseId)}`), {
    headers: { Accept: "application/json" },
  });
  return readOrThrow(res, "Could not load the application case");
}

export interface CaseDocumentEvidenceView {
  doc_id: string;
  label: string;
  verdict: string;
  added_at: string;
  evidence_pack: EvidencePack | null;
}

export interface CaseEvidenceView {
  case_id: string;
  documents: CaseDocumentEvidenceView[];
}

/** Every accumulated document's FULL evidence pack — GET /api/cases/{id}/evidence. This is what feeds
 * the case-level Underwriter Copilot (via CopilotContext.setCaseContext) so it can answer a question
 * about ANY document in the case, fetched fresh from the backend rather than only remembering the
 * single most-recently-added document in page state. */
export async function getCaseEvidence(caseId: string): Promise<CaseEvidenceView> {
  const res = await fetch(apiUrl(`/api/cases/${encodeURIComponent(caseId)}/evidence`), {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new ApiError(`Could not load the case's evidence (HTTP ${res.status})`, res.status);
  }
  return (await res.json()) as CaseEvidenceView;
}
