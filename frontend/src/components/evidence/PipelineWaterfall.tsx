import { CheckCircle2, Clock, XCircle, Minus, AlertTriangle, ChevronRight } from "lucide-react";
import type { LayerPipelineStatus, PipelineStepStatus } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

/**
 * Verification pipeline waterfall — shows all 8 layers (0–7) with their run status
 * and the tier they belong to (ADR-004 §3, CLAUDE.md §9 "verification tier reached").
 * Each layer node is color-coded and labeled so an underwriter can immediately see
 * *which* evidence was reached before the verdict was issued.
 */

const LAYER_NAMES: Record<number, string> = {
  0: "Intake",
  1: "Provenance",
  2: "VLM Read",
  3: "Claim Graph",
  4: "Rule Packs",
  5: "Anomaly",
  6: "Cross-Doc",
  7: "Decision",
};

const TIER_LABEL: Record<number, string> = {
  1: "T1",
  2: "T2",
  3: "T3",
};

interface StatusCfg {
  Icon: typeof CheckCircle2;
  iconCls: string;
  nodeCls: string;
  label: string;
}

const STATUS_CFG: Record<PipelineStepStatus, StatusCfg> = {
  PASS: {
    Icon: CheckCircle2,
    iconCls: "text-verdict-approved",
    nodeCls: "border-verdict-approved/40 bg-verdict-approved-soft",
    label: "Pass",
  },
  FAIL: {
    Icon: XCircle,
    iconCls: "text-verdict-rejected",
    nodeCls: "border-verdict-rejected/40 bg-verdict-rejected-soft",
    label: "Fail",
  },
  SKIP: {
    Icon: Minus,
    iconCls: "text-text-tertiary",
    nodeCls: "border-hairline/40 bg-canvas/20",
    label: "Skip",
  },
  NOT_EVALUATED: {
    Icon: Clock,
    iconCls: "text-verdict-pending",
    nodeCls: "border-verdict-pending/30 bg-verdict-pending-soft/40",
    label: "Pending",
  },
  ERROR: {
    Icon: AlertTriangle,
    iconCls: "text-verdict-rejected",
    nodeCls: "border-verdict-rejected/40 bg-verdict-rejected-soft",
    label: "Error",
  },
};

interface PipelineWaterfallProps {
  layers: LayerPipelineStatus[];
}

export function PipelineWaterfall({ layers }: PipelineWaterfallProps) {
  const sorted = [...layers].sort((a, b) => a.layer - b.layer);
  const ran = sorted.filter((l) => l.ran).length;

  return (
    <Panel
      title="Verification pipeline"
      aside={`${ran}/${sorted.length} layers ran`}
      ariaLabel="Verification pipeline waterfall"
    >
      <div className="overflow-x-auto pb-1">
        <div className="flex items-center gap-0">
          {sorted.map((l, idx) => {
            const cfg = STATUS_CFG[l.status] ?? STATUS_CFG["NOT_EVALUATED"];
            const isLast = idx === sorted.length - 1;
            const opacity = !l.ran && l.status === "SKIP" ? "opacity-50" : "";

            return (
              <div key={l.layer} className="flex items-center gap-0">
                {/* Layer node */}
                <div
                  className={cn(
                    "relative flex min-w-[68px] flex-col items-center gap-1 rounded-lg border px-2 py-2.5 transition-opacity",
                    cfg.nodeCls,
                    opacity,
                  )}
                  role="status"
                  aria-label={`Layer ${l.layer} ${LAYER_NAMES[l.layer] ?? l.name}: ${cfg.label}`}
                  title={`${LAYER_NAMES[l.layer] ?? l.name} · ${cfg.label}`}
                >
                  {/* Tier badge */}
                  {l.tier != null && (
                    <span className="absolute -top-2 -right-1.5 rounded-full border border-accent/30 bg-canvas px-1 text-[9px] font-bold text-accent">
                      {TIER_LABEL[l.tier]}
                    </span>
                  )}

                  {/* Layer number */}
                  <span className="text-[9px] font-bold text-text-tertiary">L{l.layer}</span>

                  {/* Status icon */}
                  <cfg.Icon size={15} className={cfg.iconCls} aria-hidden="true" />

                  {/* Layer name */}
                  <span className="text-center text-[10px] font-semibold leading-tight text-text-secondary whitespace-nowrap">
                    {LAYER_NAMES[l.layer] ?? l.name}
                  </span>

                  {/* Status label */}
                  <span className={cn("text-[9px] font-medium", cfg.iconCls)}>{cfg.label}</span>
                </div>

                {/* Connector arrow */}
                {!isLast && (
                  <ChevronRight
                    size={14}
                    className="shrink-0 text-hairline-strong"
                    aria-hidden="true"
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Tier legend */}
      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-hairline/40 pt-2.5">
        <span className="text-[10px] text-text-tertiary">Tiers:</span>
        {([1, 2, 3] as const).map((t) => (
          <span key={t} className="flex items-center gap-1 text-[10px] text-text-tertiary">
            <span className="rounded-full border border-accent/30 bg-canvas px-1 text-[9px] font-bold text-accent">
              {TIER_LABEL[t]}
            </span>
            {t === 1 && "Source-verified (cryptographic)"}
            {t === 2 && "Forensic / VLM fallback"}
            {t === 3 && "In-person live capture"}
          </span>
        ))}
      </div>
    </Panel>
  );
}
