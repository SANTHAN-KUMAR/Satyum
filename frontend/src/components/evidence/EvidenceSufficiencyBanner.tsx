import { Layers } from "lucide-react";
import type { EvidenceSufficiency } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Layer-0 evidence sufficiency strip (ADR-004 §3).
 * Tells the underwriter what confidence is achievable given the submission — before any
 * signal runs. A single-document submission with no corroboration warrants different
 * skepticism than a fully-corroborated cross-source bundle (CLAUDE.md §9).
 */

const LEVEL_CFG = {
  "single-document": {
    label: "Single document",
    description: "One document analyzed — cross-document corroboration not available",
    chipCls:
      "border-verdict-review/50 bg-verdict-review-soft text-verdict-review",
  },
  "case-context": {
    label: "Case context",
    description: "Multiple documents present — partial cross-document corroboration",
    chipCls: "border-accent/40 bg-accent/10 text-accent",
  },
  corroborated: {
    label: "Corroborated",
    description: "Cross-document consistency verified — high achievable confidence",
    chipCls: "border-verdict-approved/50 bg-verdict-approved-soft text-verdict-approved",
  },
} as const;

const CONFIDENCE_CLS: Record<string, string> = {
  LOW: "text-verdict-review",
  MEDIUM: "text-accent",
  HIGH: "text-verdict-approved",
};

interface EvidenceSufficiencyBannerProps {
  sufficiency: EvidenceSufficiency;
}

export function EvidenceSufficiencyBanner({ sufficiency }: EvidenceSufficiencyBannerProps) {
  const cfg = LEVEL_CFG[sufficiency.level];

  return (
    <div
      className="panel-muted flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5"
      role="status"
      aria-label={`Evidence sufficiency: ${cfg.label}`}
    >
      <Layers size={13} className="shrink-0 text-text-tertiary" aria-hidden="true" />
      <span className="eyebrow">Evidence sufficiency</span>

      <span
        className={cn(
          "rounded-full border px-2.5 py-0.5 text-[11px] font-semibold",
          cfg.chipCls,
        )}
      >
        {cfg.label}
      </span>

      <span className="text-xs text-text-secondary">{cfg.description}</span>

      <div className="ml-auto flex items-center gap-1.5 text-xs">
        <span className="text-text-tertiary">Achievable confidence:</span>
        <span className={cn("font-semibold", CONFIDENCE_CLS[sufficiency.achievable_confidence])}>
          {sufficiency.achievable_confidence}
        </span>
      </div>

      {sufficiency.source_types.length > 0 && (
        <span className="text-[11px] text-text-tertiary">
          {sufficiency.doc_count} doc{sufficiency.doc_count !== 1 ? "s" : ""}
          {" · "}
          {sufficiency.source_types.join(", ")}
        </span>
      )}
    </div>
  );
}
