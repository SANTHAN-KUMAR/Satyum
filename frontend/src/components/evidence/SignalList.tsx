import { Activity, ChevronRight } from "lucide-react";
import type { LayerSignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { StatusPill } from "@/components/primitives/StatusPill";
import { MODE_LABEL } from "@/lib/verdict";
import { cn } from "@/lib/cn";
import { MeasurementBreakdown } from "./MeasurementBreakdown";

interface SignalListProps {
  /** The FULL LayerSignal list (TrustScore.signals) — carries measurements for the breakdown. */
  signals: LayerSignal[];
}

type Severity = "error" | "high" | "flag" | "clean" | "pending";

function severityOf(s: LayerSignal): Severity {
  if (s.status === "ERROR") return "error";
  if (s.status === "NOT_EVALUATED") return "pending";
  const susp = s.suspicion ?? 0;
  if (susp >= 0.6) return "high";
  if (susp > 0) return "flag";
  return "clean";
}

/** Order: errors → strong flags → mild flags → clean, then pending last. */
const RANK: Record<Severity, number> = { error: 0, high: 1, flag: 2, clean: 3, pending: 4 };

/** Left stripe + suspicion-badge colour per severity (scannable findings list). */
const STRIPE: Record<Severity, string> = {
  error: "border-l-verdict-rejected",
  high: "border-l-verdict-rejected",
  flag: "border-l-verdict-review",
  clean: "border-l-verdict-approved",
  pending: "border-l-hairline",
};

function humanName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Per-signal findings — the explainability core (CLAUDE.md §9). Each row LEADS with the analyzer's
 * human reason and status; the model-internal vocabulary (layer / weight / suspicion / producing
 * mode) is demoted to one quiet technical line so it does not compete with the finding. For a
 * flagged signal the real `measurements` (e.g. exactly which arithmetic invariant broke) are
 * surfaced inline — the most compelling evidence is promoted, not hidden behind a toggle.
 *
 * Every value is from TrustScore.signals — nothing computed or invented here (§9 no fabricated data).
 */
export function SignalList({ signals }: SignalListProps) {
  const ordered = [...signals].sort((a, b) => RANK[severityOf(a)] - RANK[severityOf(b)]);

  return (
    <Panel
      title="Per-signal findings"
      icon={Activity}
      aside={`${signals.length} signal${signals.length === 1 ? "" : "s"}`}
    >
      {ordered.length === 0 ? (
        <p className="text-sm text-text-tertiary">No signals reported for this intake.</p>
      ) : (
        <ul className="space-y-2.5">
          {ordered.map((s) => {
            const sev = severityOf(s);
            const flagged = sev === "high" || sev === "flag" || sev === "error";
            const hasDetail = Object.keys(s.measurements).length > 0;
            const susp = s.suspicion;
            return (
              <li
                key={s.name}
                className={cn(
                  "rounded-lg border border-hairline border-l-2 bg-surface-muted/30 px-3.5 py-3",
                  STRIPE[sev],
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary">{humanName(s.name)}</p>
                    {s.reason && (
                      <p className="mt-0.5 text-sm leading-relaxed text-text-secondary">{s.reason}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <StatusPill status={s.status} />
                    {s.status === "VALID" && susp != null && (
                      <span
                        className={cn(
                          "tnum text-[11px] font-semibold",
                          sev === "high"
                            ? "text-verdict-rejected"
                            : sev === "flag"
                              ? "text-verdict-review"
                              : "text-text-tertiary",
                        )}
                        title="Suspicion: 0 clean → 1 maximally suspicious"
                      >
                        {Math.round(susp * 100)}% suspicion
                      </span>
                    )}
                  </div>
                </div>

                {/* Demoted technical line — visible (mode-tag invariant, §1) but quiet. */}
                <p className="mt-2 text-[11px] text-text-tertiary">
                  {MODE_LABEL[s.producing_mode] ?? s.producing_mode}-mode · layer {s.layer}
                  {s.status === "VALID" && ` · weight ${s.weight.toFixed(2)}`}
                </p>

                {hasDetail &&
                  (flagged ? (
                    // Promote the evidence: a flagged signal shows WHY inline.
                    <div className="mt-2.5 rounded-lg border border-hairline bg-surface p-3">
                      <MeasurementBreakdown measurements={s.measurements} />
                    </div>
                  ) : (
                    // Clean / pending signals keep the detail tucked away.
                    <details className="group mt-2">
                      <summary className="inline-flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-accent/80 hover:text-accent">
                        <ChevronRight
                          size={13}
                          className="transition-transform group-open:rotate-90"
                          aria-hidden="true"
                        />
                        Analysis detail
                      </summary>
                      <div className="mt-2 rounded-lg border border-hairline bg-surface p-3">
                        <MeasurementBreakdown measurements={s.measurements} />
                      </div>
                    </details>
                  ))}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
