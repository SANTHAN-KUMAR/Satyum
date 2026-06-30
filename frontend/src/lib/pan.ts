/**
 * Client-side PAN structure validation for instant inline feedback (Razorpay "fail early, locally").
 * Mirrors backend/providers/pan.py — format + the ITD 4th-char holder-type code. We NEVER claim the
 * 10th-char checksum (NSDL algorithm is non-public) or true existence (Protean-gated) — same honesty
 * as the backend. The backend remains the source of truth; this is just snappy UX.
 */

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

export const PAN_ENTITY_CODES: Record<string, string> = {
  P: "Individual",
  C: "Company",
  H: "Hindu Undivided Family (HUF)",
  F: "Firm / LLP",
  A: "Association of Persons (AOP)",
  T: "Trust",
  B: "Body of Individuals (BOI)",
  L: "Local Authority",
  J: "Artificial Juridical Person",
  G: "Government",
};

export interface PanCheck {
  ok: boolean;
  entityType: string | null;
  message: string;
}

export function validatePanStructure(raw: string): PanCheck {
  const pan = (raw || "").trim().toUpperCase();
  if (!pan) return { ok: false, entityType: null, message: "" };
  if (!PAN_RE.test(pan)) {
    return { ok: false, entityType: null, message: "Expected AAAAA9999A (5 letters, 4 digits, 1 letter)." };
  }
  const code = pan[3]!;
  const entityType = PAN_ENTITY_CODES[code] ?? null;
  if (!entityType) {
    return { ok: false, entityType: null, message: `4th character "${code}" is not a valid holder-type code.` };
  }
  return { ok: true, entityType, message: `Valid structure · ${entityType}` };
}
