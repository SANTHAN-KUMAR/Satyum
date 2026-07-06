import { useEffect, useMemo, useState } from "react";
import { FileSearch, LayoutDashboard, ListChecks } from "lucide-react";
import type { TrustScore } from "@/api/types";
import { TIER_LABEL } from "@/lib/verdict";
import { useCopilotContext } from "@/lib/CopilotContext";
import { VerdictHero } from "./VerdictHero";
import { ProvenanceCard } from "./ProvenanceCard";
import { SignalList } from "./SignalList";
import { ReasonsCard } from "./ReasonsCard";
import { PendingList } from "./PendingList";
import { DocumentPreview } from "./DocumentPreview";
import { CaseMeta } from "./CaseMeta";
import { PrivacyNote } from "./PrivacyNote";
import { EvidenceTabs, type EvidenceTabDef } from "./EvidenceTabs";
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
 * The Underwriter Evidence Console (CLAUDE.md §9, ADR-004 §3, frontend/DESIGN.md §3.1).
 *
 * Always visible: VerdictHero (verdict + trust score + recommended action) and the sufficiency banner —
 * the two facts every underwriter needs before doing anything else. Everything else lives behind tabs
 * instead of one long stacked scroll, so the console reads as a tool to navigate rather than a report to
 * page through:
 *   - Overview       — pipeline waterfall, source provenance, narrative reasons, honest pending list
 *   - Claims & rules  — VLM claim graph (cross-read verified) + deterministic rule packs + soft anomaly signals
 *   - Signals & preview — document preview with the tamper-region overlay + the full per-signal list
 * The Copilot itself moved out of a tab entirely — it's the global drawer (AppShell / GlobalCopilotDrawer)
 * so it stays reachable no matter which page the underwriter is on; this console just registers its
 * evidence pack as the drawer's active context (frontend/DESIGN.md addendum, "omnipresent copilot").
 * A tab only appears when the backend actually returned data for it — no empty/fabricated sections.
 * Every value on screen comes from real backend output — nothing is fabricated (§9).
 */
export function EvidenceConsole({ trust, previewUrl, isPdf, fileName }: EvidenceConsoleProps) {
  const pack = trust.evidence_pack;
  const tierLabel = TIER_LABEL[trust.tier_reached] ?? trust.tier_reached;
  const { setDocumentContext } = useCopilotContext();

  const hasSufficiency = trust.evidence_sufficiency != null;
  const hasPipeline = (trust.pipeline_layers?.length ?? 0) > 0;
  const hasClaimGraph = (trust.claim_graph?.length ?? 0) > 0;
  const hasRulePacks = (trust.rule_pack_results?.length ?? 0) > 0;
  const hasAnomaly = (trust.anomaly_signals?.length ?? 0) > 0;

  // Register this evidence pack as the global Copilot's active (single-document) context. Deliberately
  // NOT cleared on unmount — navigating away (e.g. to Consortium) should keep the last real analysis
  // available in the drawer, not blank it out, so the "omnipresent" copilot survives route changes.
  useEffect(() => {
    setDocumentContext(pack, fileName);
  }, [pack, fileName, setDocumentContext]);

  const tabs = useMemo<EvidenceTabDef[]>(
    () => [
      { id: "overview", label: "Overview", icon: LayoutDashboard },
      ...(hasClaimGraph || hasRulePacks || hasAnomaly
        ? [{ id: "claims", label: "Claims & rules", icon: ListChecks }]
        : []),
      { id: "signals", label: "Signals & preview", icon: FileSearch },
    ],
    [hasClaimGraph, hasRulePacks, hasAnomaly],
  );
  const [active, setActive] = useState(tabs[0]!.id);
  const activeTab = tabs.some((t) => t.id === active) ? active : tabs[0]!.id;

  return (
    <div className="animate-fade-in space-y-5">
      {/* Always visible — the 5-second scan. */}
      <VerdictHero trust={trust} />
      {hasSufficiency && <EvidenceSufficiencyBanner sufficiency={trust.evidence_sufficiency!} />}

      <EvidenceTabs tabs={tabs} active={activeTab} onChange={setActive} />

      <div role="tabpanel" id={`evidence-panel-${activeTab}`} aria-labelledby={`evidence-tab-${activeTab}`} className="space-y-5">
        {activeTab === "overview" && (
          <>
            {hasPipeline && <PipelineWaterfall layers={trust.pipeline_layers!} />}
            <ProvenanceCard provenance={trust.provenance} tierLabel={tierLabel} />
            <div className="grid gap-5 lg:grid-cols-2">
              <ReasonsCard reasons={pack.reasons} />
              <PendingList pending={pack.pending_not_evaluated} />
            </div>
          </>
        )}

        {activeTab === "claims" && (
          <>
            {hasClaimGraph && <ClaimGraphView claims={trust.claim_graph!} />}
            {hasRulePacks && <RulePackPanel packs={trust.rule_pack_results!} />}
            {hasAnomaly && <AnomalyPanel signals={trust.anomaly_signals!} />}
          </>
        )}

        {activeTab === "signals" && (
          <div className="grid gap-5 lg:grid-cols-2">
            <DocumentPreview previewUrl={previewUrl} isPdf={isPdf} fileName={fileName} regions={pack.tamper_evidence_regions} />
            {/* Full LayerSignal list (not the lossy evidence_pack projection) so per-signal
                measurement breakdowns — e.g. which arithmetic invariant broke — are available. */}
            <SignalList signals={trust.signals} />
          </div>
        )}
      </div>

      {/* Demoted audit rail — always visible, at the bottom, out of the way. */}
      <div className="flex flex-col gap-3 border-t border-hairline/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <CaseMeta trust={trust} />
        <PrivacyNote note={pack.privacy_note} />
      </div>
    </div>
  );
}
