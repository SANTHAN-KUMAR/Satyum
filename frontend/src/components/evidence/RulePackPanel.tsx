import { useState } from "react";
import { Shield, CheckCircle2, XCircle, HelpCircle, Clock, MinusCircle } from "lucide-react";
import type { RulePackResult, RuleResult, RuleStatus } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

/**
 * Layer-4 deterministic rule pack results (ADR-004 §3, §4 "rules decide").
 * One tab per domain (financial / land / legal). Each rule emits PASS / FAIL /
 * UNKNOWN / NOT_APPLICABLE / NOT_EVALUATED. FAIL rows are highlighted and expand
 * their reason so the underwriter sees exactly which invariant broke and which
 * claims from the graph the rule consumed.
 *
 * These are deterministic, classical-logic outputs — no ML in this path (CLAUDE.md §4).
 */

interface StatusCfg {
  label: string;
  Icon: typeof CheckCircle2;
  iconCls: string;
  rowCls: string;
  stripeCls: string;
}

const STATUS_CFG: Record<RuleStatus, StatusCfg> = {
  PASS: {
    label: "Pass",
    Icon: CheckCircle2,
    iconCls: "text-verdict-approved",
    rowCls: "border-hairline bg-surface-muted/30",
    stripeCls: "border-l-verdict-approved/40",
  },
  FAIL: {
    label: "Fail",
    Icon: XCircle,
    iconCls: "text-verdict-rejected",
    rowCls: "border-verdict-rejected/30 bg-verdict-rejected-soft/40",
    stripeCls: "border-l-verdict-rejected",
  },
  UNKNOWN: {
    label: "Unknown",
    Icon: HelpCircle,
    iconCls: "text-verdict-review",
    rowCls: "border-hairline bg-surface-muted/30",
    stripeCls: "border-l-verdict-review/60",
  },
  NOT_APPLICABLE: {
    label: "N/A",
    Icon: MinusCircle,
    iconCls: "text-text-tertiary",
    rowCls: "border-hairline/50 bg-canvas/20 opacity-60",
    stripeCls: "border-l-hairline/40",
  },
  NOT_EVALUATED: {
    label: "Pending",
    Icon: Clock,
    iconCls: "text-verdict-pending",
    rowCls: "border-hairline bg-surface-muted/30",
    stripeCls: "border-l-verdict-pending/40",
  },
};

const DOMAIN_LABEL: Record<string, string> = {
  financial: "Financial",
  land: "Land",
  legal: "Legal",
};

function failCount(pack: RulePackResult): number {
  return pack.rules.filter((r) => r.status === "FAIL").length;
}

function RuleRow({ rule }: { rule: RuleResult }) {
  const cfg = STATUS_CFG[rule.status] ?? STATUS_CFG["NOT_EVALUATED"];
  return (
    <div
      className={cn(
        "rounded-lg border border-l-2 px-3.5 py-2.5 transition-colors",
        cfg.rowCls,
        cfg.stripeCls,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-text-primary">{rule.description}</p>
          {rule.reason && (
            <p className="mt-0.5 text-xs leading-relaxed text-text-secondary">{rule.reason}</p>
          )}
          {rule.claims_used.length > 0 && (
            <p className="mt-1.5 flex flex-wrap gap-1">
              {rule.claims_used.map((c) => (
                <span
                  key={c}
                  className="rounded bg-canvas/60 border border-hairline px-1.5 py-px font-mono text-[10px] text-text-tertiary"
                >
                  {c}
                </span>
              ))}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1 mt-0.5">
          <cfg.Icon size={13} className={cfg.iconCls} aria-hidden="true" />
          <span className={cn("text-xs font-semibold whitespace-nowrap", cfg.iconCls)}>
            {cfg.label}
          </span>
        </div>
      </div>
    </div>
  );
}

interface RulePackPanelProps {
  packs: RulePackResult[];
}

export function RulePackPanel({ packs }: RulePackPanelProps) {
  const [activeTab, setActiveTab] = useState(0);

  if (packs.length === 0) {
    return (
      <Panel title="Rule packs" icon={Shield}>
        <p className="text-sm text-text-secondary">No rule pack results for this document type.</p>
      </Panel>
    );
  }

  const totalRules = packs.reduce((acc, p) => acc + p.rules.length, 0);
  const totalFails = packs.reduce((acc, p) => acc + failCount(p), 0);
  const activePack = packs[activeTab] ?? packs[0];
  // packs.length > 0 is guaranteed by the early return above, so activePack is always defined
  if (!activePack) return null;

  return (
    <Panel
      title="Rule packs (deterministic)"
      icon={Shield}
      aside={
        <span className="flex items-center gap-2 text-[11px] text-text-tertiary">
          <span>{totalRules} rules</span>
          {totalFails > 0 && (
            <span className="rounded-full border border-verdict-rejected/30 bg-verdict-rejected-soft px-2 py-0.5 font-semibold text-verdict-rejected">
              {totalFails} failed
            </span>
          )}
        </span>
      }
      ariaLabel="Deterministic rule pack results"
    >
      {/* Domain tabs — only show if more than one domain */}
      {packs.length > 1 && (
        <div
          className="mb-3 flex gap-0.5 border-b border-hairline/50"
          role="tablist"
          aria-label="Rule pack domains"
        >
          {packs.map((pack, i) => {
            const fails = failCount(pack);
            const isActive = i === activeTab;
            return (
              <button
                key={pack.domain}
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(i)}
                className={cn(
                  "flex items-center gap-1.5 rounded-t-md px-3 py-1.5 text-xs font-semibold transition-colors",
                  isActive
                    ? "border-b-2 border-accent bg-accent/5 text-accent"
                    : "text-text-secondary hover:text-text-primary",
                )}
              >
                {DOMAIN_LABEL[pack.domain] ?? pack.domain}
                {fails > 0 && (
                  <span className="rounded-full border border-verdict-rejected/30 bg-verdict-rejected-soft px-1.5 py-0.5 text-[10px] text-verdict-rejected">
                    {fails}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="space-y-2" role={packs.length > 1 ? "tabpanel" : undefined}>
        {activePack.rules.length === 0 ? (
          <p className="text-sm text-text-secondary">No rules configured for this domain.</p>
        ) : (
          activePack.rules.map((rule) => <RuleRow key={rule.rule_id} rule={rule} />)
        )}
      </div>
    </Panel>
  );
}
