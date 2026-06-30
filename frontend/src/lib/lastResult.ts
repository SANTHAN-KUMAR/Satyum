import type { TrustScore } from "@/api/types";

/**
 * A tiny module store so the applicant onboarding flow can hand its verified case to the underwriter
 * console (no global state library needed). The console reads this on mount; onboarding sets it on
 * submit. Holds only an object URL for the local preview — never round-trips the document (§10).
 */
export interface LastCase {
  trust: TrustScore;
  fileName: string;
  previewUrl: string | null;
  isPdf: boolean;
}

let last: LastCase | null = null;

export function setLastCase(c: LastCase): void {
  last = c;
}

export function getLastCase(): LastCase | null {
  return last;
}
