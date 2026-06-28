/**
 * Verdict / status / score-band presentation logic — the single source of UI semantics so colour,
 * label and meaning never drift between components (CLAUDE.md §9: "three honest verdict states,
 * unmistakable" + "no green pass for something that didn't run").
 *
 * The score-band thresholds mirror backend/app/config.py (approve_at=85, review_at=60). They are
 * presentation labels only — the verdict itself ALWAYS comes from the backend, never recomputed here
 * (CLAUDE.md §9 "no fabricated UI data"). If the backend recalibrates, update BANDS to match.
 */

import type { SignalStatus, Verdict } from "@/api/types";

/** Verdict bands from backend/app/config.py — keep in lockstep. */
export const BANDS = {
  approveAt: 85,
  reviewAt: 60,
} as const;

export interface VerdictTheme {
  label: string;
  glyph: string; // a textual mark; the live UI pairs it with an icon + aria text, never colour alone
  /** Tailwind utility groups. Colour is NEVER the only signal — always paired with glyph + label. */
  text: string;
  bg: string;
  border: string;
  ring: string;
  /** Stroke colour for the gauge arc / charts (hex, for SVG). */
  stroke: string;
}

export const VERDICT_THEME: Record<Verdict, VerdictTheme> = {
  APPROVED: {
    label: "Approved",
    glyph: "✓",
    text: "text-verdict-approved",
    bg: "bg-verdict-approved-soft",
    border: "border-verdict-approved/60",
    ring: "ring-verdict-approved/40",
    stroke: "#16a34a",
  },
  REVIEW: {
    label: "Review",
    glyph: "!",
    text: "text-verdict-review",
    bg: "bg-verdict-review-soft",
    border: "border-verdict-review/60",
    ring: "ring-verdict-review/40",
    stroke: "#d97706",
  },
  REJECTED: {
    label: "Rejected",
    glyph: "✕",
    text: "text-verdict-rejected",
    bg: "bg-verdict-rejected-soft",
    border: "border-verdict-rejected/60",
    ring: "ring-verdict-rejected/40",
    stroke: "#dc2626",
  },
};

export interface StatusTheme {
  /** The honest UI label. NOT_EVALUATED renders as "Pending" per CLAUDE.md §3.4 / §9. */
  label: string;
  text: string;
  bg: string;
  border: string;
  dot: string;
}

export const STATUS_THEME: Record<SignalStatus, StatusTheme> = {
  VALID: {
    label: "Valid",
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    dot: "bg-emerald-400",
  },
  NOT_EVALUATED: {
    label: "Pending", // honestly distinct from pass/fail (CLAUDE.md §3.4)
    text: "text-verdict-pending",
    bg: "bg-verdict-pending-soft",
    border: "border-verdict-pending/30",
    dot: "bg-verdict-pending",
  },
  ERROR: {
    label: "Error",
    text: "text-verdict-rejected",
    bg: "bg-verdict-rejected-soft",
    border: "border-verdict-rejected/40",
    dot: "bg-verdict-rejected",
  },
};

/** The labelled gauge bands, drawn as the coloured backing arc with thresholds called out. */
export interface ScoreBand {
  label: string;
  from: number; // inclusive lower bound on the 0..100 scale
  to: number; // exclusive upper bound (100 is inclusive on the top band)
  color: string; // hex for the SVG arc
}

export const SCORE_BANDS: ScoreBand[] = [
  { label: "Reject", from: 0, to: BANDS.reviewAt, color: "#dc2626" },
  { label: "Review", from: BANDS.reviewAt, to: BANDS.approveAt, color: "#d97706" },
  { label: "Approve", from: BANDS.approveAt, to: 100, color: "#16a34a" },
];

/** Human-readable tier label for TrustScore.tier_reached. */
export const TIER_LABEL: Record<string, string> = {
  "source-verified": "Tier 1 · Source-verified (cryptographic)",
  "forensic-fallback": "Tier 2 · Forensic fallback",
  "in-person-capture": "Tier 3 · In-person live capture",
};

/** Producing-mode tag label for a signal (the mode-tagging invariant made visible, CLAUDE.md §1). */
export const MODE_LABEL: Record<string, string> = {
  FILE: "File",
  CAMERA: "Camera",
  ANY: "Any medium",
};
