/**
 * ⚠ SAMPLE FIXTURE — NOT REAL BACKEND DATA.
 *
 * This is a hand-authored TrustScore used ONLY by the clearly-labelled "Sample view" (a
 * Storybook-style local preview) so the console's layout can be inspected without a running backend.
 * It is NEVER imported by the live FILE or CAMERA paths, which render only real /api/verify output
 * (CLAUDE.md §9: "no fabricated UI data ... a small dev fixture ONLY for ... local view clearly
 * marked as sample").
 *
 * The shape is produced by hand to match backend/risk/evidence.py::build_evidence_pack exactly. It
 * depicts a tampered statement (broken running balance) so every console region has something to show.
 */

import type { TrustScore } from "@/api/types";

export const SAMPLE_TRUST_SCORE: TrustScore = {
  session_id: "SAMPLE-0000-DEMO",
  intake_mode: "FILE",
  doc_type: "bank_statement",
  provenance: {
    verified: false,
    method: "none",
    detail: "No embedded signature found; routed to Tier-2 forensic fallback.",
    tampered: false,
  },
  trust_score: 41.5,
  verdict: "REJECTED",
  tier_reached: "forensic-fallback",
  fail_closed: false,
  signals: [
    {
      name: "arithmetic_consistency",
      layer: 3,
      mode: "ANY",
      status: "VALID",
      suspicion: 0.9,
      weight: 0.4,
      reason: "1 invariant(s) broken — likely edited figure(s)",
      producing_mode: "FILE",
      evidence_regions: [
        {
          bbox: [612, 884, 150, 26],
          label: "running_balance: expected 48250.00, printed 58250.00",
          source: "arithmetic_consistency",
        },
      ],
      measurements: {
        checks_run: 6,
        violations: [
          {
            kind: "running_balance",
            index: 7,
            expected: "48250.00",
            printed: "58250.00",
            delta: "10000.00",
          },
        ],
      },
    },
    {
      name: "metadata_structure",
      layer: 3,
      mode: "FILE",
      status: "VALID",
      suspicion: 0.2,
      weight: 0.15,
      reason: "Producer string changed after initial creation; one incremental update present.",
      producing_mode: "FILE",
      evidence_regions: [],
      measurements: {},
    },
    {
      name: "phash_resubmission",
      layer: 3,
      mode: "ANY",
      status: "VALID",
      suspicion: 0.0,
      weight: 0.15,
      reason: "No perceptual-hash match against the fraud-ring corpus.",
      producing_mode: "ANY",
      evidence_regions: [],
      measurements: {},
    },
    {
      name: "signature_pades",
      layer: 1,
      mode: "FILE",
      status: "NOT_EVALUATED",
      suspicion: null,
      weight: 0.0,
      reason: "No PAdES/CMS signature present on the document.",
      producing_mode: "FILE",
      evidence_regions: [],
      measurements: {},
    },
    {
      name: "active_challenge",
      layer: 4,
      mode: "CAMERA",
      status: "NOT_EVALUATED",
      suspicion: null,
      weight: 0.0,
      reason: "Camera-only signal; not applicable on a file intake.",
      producing_mode: "CAMERA",
      evidence_regions: [],
      measurements: {},
    },
  ],
  evidence_pack: {
    session_id: "SAMPLE-0000-DEMO",
    document_type: "bank_statement",
    intake_mode: "FILE",
    tier_reached: "forensic-fallback",
    provenance: {
      verified: false,
      method: "none",
      detail: "No embedded signature found; routed to Tier-2 forensic fallback.",
      tampered: false,
    },
    trust_score: 41.5,
    verdict: "REJECTED",
    fail_closed: false,
    recommended_action:
      "Reject / escalate to fraud ops — strong tampering or failed verification.",
    reasons: [
      "arithmetic_consistency: 1 invariant(s) broken — likely edited figure(s)",
      "metadata_structure: Producer string changed after initial creation; one incremental update present.",
    ],
    signals: [
      {
        name: "arithmetic_consistency",
        layer: 3,
        producing_mode: "FILE",
        status: "VALID",
        suspicion: 0.9,
        weight: 0.4,
        reason: "1 invariant(s) broken — likely edited figure(s)",
      },
      {
        name: "metadata_structure",
        layer: 3,
        producing_mode: "FILE",
        status: "VALID",
        suspicion: 0.2,
        weight: 0.15,
        reason: "Producer string changed after initial creation; one incremental update present.",
      },
      {
        name: "phash_resubmission",
        layer: 3,
        producing_mode: "ANY",
        status: "VALID",
        suspicion: 0.0,
        weight: 0.15,
        reason: "No perceptual-hash match against the fraud-ring corpus.",
      },
      {
        name: "signature_pades",
        layer: 1,
        producing_mode: "FILE",
        status: "NOT_EVALUATED",
        suspicion: null,
        weight: 0.0,
        reason: "No PAdES/CMS signature present on the document.",
      },
      {
        name: "active_challenge",
        layer: 4,
        producing_mode: "CAMERA",
        status: "NOT_EVALUATED",
        suspicion: null,
        weight: 0.0,
        reason: "Camera-only signal; not applicable on a file intake.",
      },
    ],
    pending_not_evaluated: [
      { name: "signature_pades", reason: "No PAdES/CMS signature present on the document." },
      { name: "active_challenge", reason: "Camera-only signal; not applicable on a file intake." },
    ],
    tamper_evidence_regions: [
      {
        bbox: [612, 884, 150, 26],
        label: "running_balance: expected 48250.00, printed 58250.00",
        source: "arithmetic_consistency",
        suspicion: 0.9,
      },
    ],
    privacy_note:
      "Ephemeral processing: camera frames and document content are held in memory for the session only and are never persisted. This record stores decision metadata and signal digests, not the document or any imagery.",
  },
};
