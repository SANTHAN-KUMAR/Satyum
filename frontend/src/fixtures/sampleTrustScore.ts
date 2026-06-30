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

import type {
  TrustScore,
  EvidenceSufficiency,
  Claim,
  RulePackResult,
  AnomalySignal,
  LayerPipelineStatus,
} from "@/api/types";

// ---------------------------------------------------------------------------
// v2 fixture data — exercises every new console section (ADR-004).
// The scenario: a tampered bank statement where the running balance was edited
// from ₹48,250 to ₹58,250 — arithmetic catches it; cross-read agrees on the
// printed (wrong) number; rule pack finds the invariant break.
// ---------------------------------------------------------------------------

const SAMPLE_EVIDENCE_SUFFICIENCY: EvidenceSufficiency = {
  level: "single-document",
  doc_count: 1,
  source_types: ["pdf"],
  achievable_confidence: "LOW",
};

const SAMPLE_CLAIM_GRAPH: Claim[] = [
  {
    subject: "bank_statement_1",
    predicate: "account_number",
    value: "40123456789",
    value_type: "ID",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [48, 120, 180, 20],
      confidence: 0.97,
      source: "vlm",
      corroborating_read: "40123456789",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
  {
    subject: "bank_statement_1",
    predicate: "account_holder",
    value: "Rajesh Kumar",
    value_type: "NAME",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [48, 98, 200, 18],
      confidence: 0.95,
      source: "vlm",
      corroborating_read: "Rajesh Kumar",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
  {
    subject: "bank_statement_1",
    predicate: "ifsc_code",
    value: "CNRB0000123",
    value_type: "ID",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [250, 120, 140, 20],
      confidence: 0.99,
      source: "vlm",
      corroborating_read: "CNRB0000123",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
  {
    subject: "bank_statement_1",
    predicate: "opening_balance",
    value: "50250.00",
    value_type: "MONEY",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [612, 620, 120, 20],
      confidence: 0.96,
      source: "vlm",
      corroborating_read: "50250.00",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
  {
    subject: "bank_statement_1",
    predicate: "transaction_debit[row=6]",
    value: "2000.00",
    value_type: "MONEY",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [520, 860, 90, 20],
      confidence: 0.93,
      source: "vlm",
      corroborating_read: "2000.00",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
  {
    subject: "bank_statement_1",
    predicate: "running_balance[row=7]",
    // VLM and OCR both read the PRINTED (tampered) value correctly.
    // The arithmetic rule engine is what flags the discrepancy — this claim is
    // honestly VERIFIED (both readers agree on what's printed); the edit is
    // caught by the financial rule pack, not by cross-read disagreement.
    value: "58250.00",
    value_type: "MONEY",
    provenance: {
      doc_id: "bank_statement_1",
      page: 1,
      bbox: [612, 884, 150, 26],
      confidence: 0.98,
      source: "vlm",
      corroborating_read: "58250.00",
      cross_read_agree: true,
    },
    status: "VERIFIED",
  },
];

const SAMPLE_RULE_PACKS: RulePackResult[] = [
  {
    domain: "financial",
    rules: [
      {
        rule_id: "fin_bal_001",
        description: "Running balance carry-forward invariant",
        status: "FAIL",
        reason:
          "Row 7: prior_balance(50250.00) − debit(2000.00) = expected(48250.00); printed 58250.00 → delta +10000.00",
        claims_used: ["running_balance[row=7]", "transaction_debit[row=6]", "opening_balance"],
      },
      {
        rule_id: "fin_bal_002",
        description: "Debit / credit / net balance consistency",
        status: "UNKNOWN",
        reason:
          "Insufficient transaction rows extracted to verify full period net — partial check only.",
        claims_used: [],
      },
      {
        rule_id: "fin_bal_003",
        description: "Opening balance matches prior period closing",
        status: "PASS",
        reason: "Opening balance (50250.00) is consistent with the prior-period closing figure.",
        claims_used: ["opening_balance"],
      },
      {
        rule_id: "fin_id_001",
        description: "Account number format (IFSC region code)",
        status: "PASS",
        reason: "Account number passes CNRB prefix validation for this branch IFSC.",
        claims_used: ["account_number", "ifsc_code"],
      },
    ],
  },
];

const SAMPLE_ANOMALY_SIGNALS: AnomalySignal[] = [
  {
    kind: "round_number_delta",
    reason:
      "The balance discrepancy is an exact round number (₹10,000.00). Manual single-field edits typically produce round-number changes; a genuine transaction rarely aligns to an exact round figure.",
    verdict_impact: "REVIEW",
    is_ml: false,
  },
];

const SAMPLE_PIPELINE_LAYERS: LayerPipelineStatus[] = [
  { layer: 0, name: "Intake", ran: true, status: "PASS", tier: null },
  { layer: 1, name: "Provenance", ran: true, status: "SKIP", tier: 1 },
  { layer: 2, name: "VLM Read", ran: true, status: "PASS", tier: 2 },
  { layer: 3, name: "Claim Graph", ran: true, status: "PASS", tier: 2 },
  { layer: 4, name: "Rule Packs", ran: true, status: "FAIL", tier: 2 },
  { layer: 5, name: "Anomaly", ran: true, status: "PASS", tier: 2 },
  { layer: 6, name: "Cross-Doc", ran: false, status: "SKIP", tier: null },
  { layer: 7, name: "Decision", ran: true, status: "PASS", tier: null },
];

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
  // v2 optional fields — exercise every new console section
  evidence_sufficiency: SAMPLE_EVIDENCE_SUFFICIENCY,
  claim_graph: SAMPLE_CLAIM_GRAPH,
  rule_pack_results: SAMPLE_RULE_PACKS,
  anomaly_signals: SAMPLE_ANOMALY_SIGNALS,
  pipeline_layers: SAMPLE_PIPELINE_LAYERS,
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
