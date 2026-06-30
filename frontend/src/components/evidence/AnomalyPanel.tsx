import { TrendingUp, FlaskConical } from "lucide-react";
import type { AnomalySignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";

/**
 * Layer-5 hybrid anomaly intelligence (ADR-004 §3 — "Anomaly Intelligence").
 *
 * Two sub-lanes:
 *   1. Deterministic stats backbone — rule-based pattern detection (sudden salary
 *      jumps, round-number deltas, cherry-picked windows, etc.). Hard soft-cap: REVIEW.
 *   2. Optional ML lane — flag-gated, never on the decision path, labeled "experimental".
 *
 * Both lanes emit REVIEW-only signals. Neither can harden to REJECT (CLAUDE.md §4,
 * ADR-004 §3 "Hybrid anomaly: soft REVIEW-only signals; ML lane separable, experimental").
 * This is clearly communicated in the panel header so the underwriter doesn't over-read them.
 */

function humanKind(kind: string): string {
  return kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface AnomalyPanelProps {
  signals: AnomalySignal[];
}

export function AnomalyPanel({ signals }: AnomalyPanelProps) {
  const statsBacked = signals.filter((s) => !s.is_ml);
  const mlBacked = signals.filter((s) => s.is_ml);

  return (
    <Panel
      title="Anomaly intelligence"
      icon={TrendingUp}
      aside={
        <span className="rounded-full border border-verdict-review/40 bg-verdict-review-soft px-2.5 py-0.5 text-[10px] font-semibold text-verdict-review">
          REVIEW-only · soft signals
        </span>
      }
      ariaLabel="Layer 5 anomaly intelligence signals"
    >
      <p className="mb-4 text-[11px] leading-relaxed text-slate-500">
        Soft signals — these can raise to{" "}
        <span className="font-semibold text-verdict-review">REVIEW</span> but never to REJECT.
        They surface statistical patterns consistent with tampering and warrant underwriter
        judgment, not automatic rejection.
      </p>

      {signals.length === 0 ? (
        <p className="text-sm text-slate-400">No anomaly signals raised for this document.</p>
      ) : (
        <div className="space-y-5">
          {/* Stats backbone — deterministic, higher weight */}
          {statsBacked.length > 0 && (
            <div>
              <p className="eyebrow mb-2">Stats backbone</p>
              <div className="space-y-2">
                {statsBacked.map((sig, i) => (
                  <div
                    key={`stat-${sig.kind}-${i}`}
                    className="rounded-lg border border-l-2 border-verdict-review/30 border-l-verdict-review/70 bg-verdict-review-soft/30 px-3.5 py-2.5"
                  >
                    <p className="text-xs font-semibold text-verdict-review">
                      {humanKind(sig.kind)}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-300">{sig.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ML lane — experimental, labeled clearly, lower weight */}
          {mlBacked.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <p className="eyebrow">ML lane</p>
                <span className="flex items-center gap-1 rounded-full border border-hairline bg-canvas/60 px-2 py-0.5 text-[10px] font-medium text-slate-400">
                  <FlaskConical size={11} aria-hidden="true" />
                  experimental
                </span>
              </div>
              <div className="space-y-2">
                {mlBacked.map((sig, i) => (
                  <div
                    key={`ml-${sig.kind}-${i}`}
                    className="rounded-lg border border-hairline bg-surface-2/30 px-3.5 py-2.5 opacity-85"
                  >
                    <p className="text-xs font-semibold text-slate-300">{humanKind(sig.kind)}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{sig.reason}</p>
                    <p className="mt-1.5 text-[10px] italic text-slate-600">
                      ML lane — experimental · REVIEW-only · not on the decision path
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
