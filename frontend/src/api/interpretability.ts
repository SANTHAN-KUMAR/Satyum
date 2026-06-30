import { apiUrl, ApiError } from "./client";

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
  tool_calls_made: Array<{ tool: string; arguments: any }>;
}

export async function getNarrative(evidencePack: any): Promise<NarrativeReport> {
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

export async function askCopilot(evidencePack: any, question: string, history: CopilotMessage[] = []): Promise<CopilotResponse> {
  const res = await fetch(apiUrl(`/api/interpret/ask`), {
    method: "POST",
    headers: { 
      "Accept": "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ evidence_pack: evidencePack, question, history }),
  });
  
  if (!res.ok) {
    throw new ApiError(`Failed to ask copilot (HTTP ${res.status})`, res.status);
  }
  
  return (await res.json()) as CopilotResponse;
}
