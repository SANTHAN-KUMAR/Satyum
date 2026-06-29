import type { TrustScore } from "@/api/types";
import { TIER_LABEL } from "@/lib/verdict";
import { VerdictHero } from "./VerdictHero";
import { ProvenanceCard } from "./ProvenanceCard";
import { SignalList } from "./SignalList";
import { ReasonsCard } from "./ReasonsCard";
import { PendingList } from "./PendingList";
import { DocumentPreview } from "./DocumentPreview";
import { CaseMeta } from "./CaseMeta";
import { PrivacyNote } from "./PrivacyNote";
// v2 progressive-evidence sections (ADR-004) — rendered when the backend sends the
// optional v2 fields. Absent in v1 responses; each import is guarded by the field
// check below so the console degrades cleanly on a v1 trust score.
import { EvidenceSufficiencyBanner } from "./EvidenceSufficiencyBanner";
import { PipelineWaterfall } from "./PipelineWaterfall";
import { ClaimGraphView } from "./ClaimGraphView";
import { RulePackPanel } from "./RulePackPanel";
import { AnomalyPanel } from "./AnomalyPanel";

interface EvidenceConsoleProps {
  trust: TrustScore;
  /** Locally-held preview of the intake (image object URL), if any — never round-trips the server. */
  previewUrl: string | null;
  isPdf: boolean;
  fileName: string;
}

/**
 * The Underwriter Evidence Console (CLAUDE.md §9, ADR-004 §3).
 *
 * Layout — v2 progressive evidence hierarchy:
 *   1. VerdictHero         — dominant verdict + trust score + recommended action
 *   2. Sufficiency banner  — Layer 0: achievable confidence given the submission
 *   3. Pipeline waterfall  — Layers 0–7 at a glance: what ran, what tier was reached
 *   4. ProvenanceCard      — Tier-1 cryptographic result (or its absence)
 *   5. ClaimGraphView      — Tier-2/3 VLM extraction + OCR cross-read per claim
 *   6. RulePackPanel       — Tier-4 deterministic rule results per domain
 *   7. AnomalyPanel        — Layer-5 soft signals (REVIEW-only, labeled experimental for ML lane)
 *   8. DocumentPreview + SignalList — tamper-region overlay + per-signal findings
 *   9. ReasonsCard + PendingList   — narrative + honest not-evaluated list
 *  10. CaseMeta + PrivacyNote      — demoted audit rail
 *
 * Sections 2–7 only render when the backend returns the corresponding optional v2 field.
 * Every value on screen comes from real backend output — nothing is fabricated (§9).
 */
export function EvidenceConsole({ trust, previewUrl, isPdf, fileName }: EvidenceConsoleProps) {
  const pack = trust.evidence_pack;
  const tierLabel = TIER_LABEL[trust.tier_reached] ?? trust.tier_reached;

  // v2 optional fields — present only when backend sends them
  const hasSufficiency = trust.evidence_sufficiency != null;
  const hasPipeline = (trust.pipeline_layers?.length ?? 0) > 0;
  const hasClaimGraph = (trust.claim_graph?.length ?? 0) > 0;
  const hasRulePacks = (trust.rule_pack_results?.length ?? 0) > 0;
  const hasAnomaly = (trust.anomaly_signals?.length ?? 0) > 0;

  return (
    <div className="animate-fade-in space-y-5">
      {/* 1 — dominant verdict + trust score + recommended action */}
      <VerdictHero trust={trust} />

      {/* 2 — Layer-0 evidence sufficiency: achievable confidence given the submission */}
      {hasSufficiency && (
        <EvidenceSufficiencyBanner sufficiency={trust.evidence_sufficiency!} />
      )}

      {/* 3 — Pipeline waterfall: which layers ran, at what tier */}
      {hasPipeline && <PipelineWaterfall layers={trust.pipeline_layers!} />}

      {/* 4 — Tier-1 cryptographic provenance result (or its absence) */}
      <ProvenanceCard provenance={trust.provenance} tierLabel={tierLabel} />

      {/* 5 — Claim graph: VLM extraction + OCR cross-read (Tier-2/3, Layer 2+3) */}
      {hasClaimGraph && <ClaimGraphView claims={trust.claim_graph!} />}

      {/* 6 — Deterministic rule pack results per domain (Tier-2, Layer 4) */}
      {hasRulePacks && <RulePackPanel packs={trust.rule_pack_results!} />}

      {/* 7 — Anomaly intelligence: soft REVIEW-only signals (Layer 5) */}
      {hasAnomaly && <AnomalyPanel signals={trust.anomaly_signals!} />}

      {/* 8 — Primary tamper evidence: document preview + tamper-region overlay, alongside
               the per-signal findings with inline arithmetic breakdown for flagged signals. */}
      <div className="grid gap-5 lg:grid-cols-2">
        <DocumentPreview
          previewUrl={previewUrl}
          isPdf={isPdf}
          fileName={fileName}
          regions={pack.tamper_evidence_regions}
        />
        {/* Full LayerSignal list (not the lossy evidence_pack projection) so per-signal
            measurement breakdowns — e.g. which arithmetic invariant broke — are available. */}
        <SignalList signals={trust.signals} />
      </div>

      {/* 9 — Supporting narrative: why, and what was honestly not evaluated */}
      <div className="grid gap-5 lg:grid-cols-2">
        <ReasonsCard reasons={pack.reasons} />
        <PendingList pending={pack.pending_not_evaluated} />
      </div>

      {/* 10 — Demoted audit rail: case metadata + privacy note */}
      <div className="flex flex-col gap-3 border-t border-hairline/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <CaseMeta trust={trust} />
        <PrivacyNote note={pack.privacy_note} />
      </div>
    </div>
  );
}
