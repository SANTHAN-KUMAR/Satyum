import { ChevronRight } from "lucide-react";
import type { BundleDocument, BundleTrustScore } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { Tag } from "@/components/primitives/Tag";
import { TIER_LABEL, VERDICT_THEME } from "@/lib/verdict";
import { cn } from "@/lib/cn";
import { VerdictBanner } from "./VerdictBanner";
import { TrustGauge } from "./TrustGauge";
import { CrossDocumentGraph } from "./CrossDocumentGraph";
import { ReasonsCard } from "./ReasonsCard";
import { SignalList } from "./SignalList";

/**
 * The bundle evidence console — the cross-document view (ADR-003 #3). Shows the bundle-level verdict
 * and score, the cross-document identity graph (the differentiator), the aggregate reasons, and each
 * document's own verdict (expandable to its full per-signal breakdown). Every value is from the
 * BundleTrustScore — nothing fabricated (CLAUDE.md §9). The bundle score is floored by the cross-doc
 * check independently of any single document, so an identity mismatch rejects even a clean bundle.
 */
export function BundleConsole({ bundle }: { bundle: BundleTrustScore }) {
  const labels = bundle.documents.map((d) => d.label);

  return (
    <div className="animate-fade-in space-y-4">
      {/* Hero: bundle verdict + score. */}
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <VerdictBanner verdict={bundle.bundle_verdict} failClosed={bundle.fail_closed} />
        <Panel title="Bundle trust score" aside={`${bundle.document_count} documents`}>
          <TrustGauge score={bundle.bundle_score} verdict={bundle.bundle_verdict} />
        </Panel>
      </div>

      {/* The cross-document consistency graph — the headline of bundle mode. */}
      <CrossDocumentGraph cross={bundle.cross_document} documentLabels={labels} />

      {bundle.reasons.length > 0 && <ReasonsCard reasons={bundle.reasons} />}

      {/* Per-document verdicts, each expandable to its full evidence. */}
      <Panel title="Per-document verdicts" aside={`${bundle.documents.length} documents`}>
        <ul className="space-y-3">
          {bundle.documents.map((doc) => (
            <DocumentRow key={doc.label} doc={doc} />
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function nodeLabel(label: string): string {
  const idx = label.indexOf(":");
  return idx >= 0 ? label.slice(idx + 1) : label;
}

function DocumentRow({ doc }: { doc: BundleDocument }) {
  const { trust } = doc;
  const theme = VERDICT_THEME[trust.verdict];
  const tier = TIER_LABEL[trust.tier_reached] ?? trust.tier_reached;

  return (
    <li className="rounded-lg border border-hairline bg-canvas/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold",
            theme.text,
            theme.bg,
            theme.border,
          )}
        >
          <theme.Icon size={13} strokeWidth={2.25} aria-hidden="true" />
          {theme.label}
        </span>
        <span className="text-sm font-medium text-slate-100">{nodeLabel(doc.label)}</span>
        {trust.provenance.verified && <Tag tone="accent">source-verified</Tag>}
        {trust.provenance.tampered && <Tag tone="warn">tampered signature</Tag>}
        <Tag className="ml-auto" title={tier}>
          score {trust.trust_score.toFixed(0)}
        </Tag>
      </div>
      <p className="mt-1 pl-1 text-xs text-slate-500">{tier}</p>

      <details className="group mt-2 pl-1">
        <summary className="inline-flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-accent/80 hover:text-accent">
          <ChevronRight
            size={13}
            className="transition-transform group-open:rotate-90"
            aria-hidden="true"
          />
          <span className="group-open:hidden">Show this document's signals</span>
          <span className="hidden group-open:inline">Hide this document's signals</span>
        </summary>
        <div className="mt-3 space-y-3">
          <SignalList signals={trust.signals} />
          {trust.evidence_pack.reasons.length > 0 && (
            <ReasonsCard reasons={trust.evidence_pack.reasons} />
          )}
        </div>
      </details>
    </li>
  );
}
