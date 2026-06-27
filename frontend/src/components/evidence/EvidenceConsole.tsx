import type { TrustScore } from "@/api/types";
import { TIER_LABEL } from "@/lib/verdict";
import { Panel } from "@/components/primitives/Panel";
import { CaseMeta } from "./CaseMeta";
import { VerdictBanner } from "./VerdictBanner";
import { TrustGauge } from "./TrustGauge";
import { ProvenanceCard } from "./ProvenanceCard";
import { SignalList } from "./SignalList";
import { ReasonsCard } from "./ReasonsCard";
import { PendingList } from "./PendingList";
import { RecommendedAction } from "./RecommendedAction";
import { DocumentPreview } from "./DocumentPreview";
import { PrivacyNote } from "./PrivacyNote";

interface EvidenceConsoleProps {
  trust: TrustScore;
  /** Locally-held preview of the intake (image object URL), if any — never round-trips the server. */
  previewUrl: string | null;
  isPdf: boolean;
  fileName: string;
}

/**
 * The Underwriter Evidence Console (CLAUDE.md §9) — the explainability hero. Composes the verdict,
 * the trust gauge, provenance + tier, the document preview with the tamper-evidence overlay, the
 * per-signal list (status + producing-mode tag), the reasons, the recommended action, the
 * not-evaluated/pending list, and the privacy note. Every value is read from the TrustScore /
 * embedded evidence_pack — nothing is fabricated client-side.
 */
export function EvidenceConsole({ trust, previewUrl, isPdf, fileName }: EvidenceConsoleProps) {
  const pack = trust.evidence_pack;
  const tierLabel = TIER_LABEL[trust.tier_reached] ?? trust.tier_reached;

  return (
    <div className="animate-fade-in space-y-4">
      <CaseMeta trust={trust} />

      {/* Verdict + gauge — the hero row. */}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-4">
          <VerdictBanner verdict={trust.verdict} failClosed={trust.fail_closed} />
          <RecommendedAction action={pack.recommended_action} verdict={trust.verdict} />
        </div>
        <Panel title="Trust score" aside={tierLabel}>
          <TrustGauge score={trust.trust_score} verdict={trust.verdict} />
        </Panel>
      </div>

      <ProvenanceCard provenance={trust.provenance} tierLabel={tierLabel} />

      {/* Document + tamper overlay alongside the signal explainability. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <DocumentPreview
          previewUrl={previewUrl}
          isPdf={isPdf}
          fileName={fileName}
          regions={pack.tamper_evidence_regions}
        />
        <div className="flex flex-col gap-4">
          <SignalList signals={pack.signals} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ReasonsCard reasons={pack.reasons} />
        <PendingList pending={pack.pending_not_evaluated} />
      </div>

      <PrivacyNote note={pack.privacy_note} />
    </div>
  );
}
