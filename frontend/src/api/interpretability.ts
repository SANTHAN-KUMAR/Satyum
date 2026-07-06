import { apiUrl, ApiError } from "./client";
import type { EvidencePack } from "./types";

export interface NarrativeReport {
  session_id: string;
  verdict: string;
  summary_paragraph: string;
  findings_paragraph: string;
  action_paragraph: string;
  is_fallback: boolean;
}

export interface CopilotMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string;
}

export interface CopilotResponse {
  response: string;
  tool_calls_made: Array<{ tool: string; arguments: Record<string, unknown> }>;
}

export async function getNarrative(evidencePack: EvidencePack): Promise<NarrativeReport> {
  const res = await fetch(apiUrl(`/api/interpret/narrative`), {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ evidence_pack: evidencePack }),
  });

  if (!res.ok) {
    throw new ApiError(`Failed to fetch narrative (HTTP ${res.status})`, res.status);
  }

  return (await res.json()) as NarrativeReport;
}

/**
 * `caseDocuments` maps a human label (a filename, or a doc type) to that document's full evidence
 * pack. A single-document Console session sends a one-entry map; the case page sends every document
 * accumulated in the case so far — the backend's tools (interpretability/tools.py) can then answer a
 * question about any of them, not just the one most recently added (matches app/routes/interpret.py's
 * CopilotRequest.case_documents contract).
 */
export async function askCopilot(
  caseDocuments: Record<string, EvidencePack>,
  question: string,
  history: CopilotMessage[] = [],
): Promise<CopilotResponse> {
  const res = await fetch(apiUrl(`/api/interpret/ask`), {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ case_documents: caseDocuments, question, history }),
  });

  if (!res.ok) {
    throw new ApiError(`Failed to ask copilot (HTTP ${res.status})`, res.status);
  }

  return (await res.json()) as CopilotResponse;
}
