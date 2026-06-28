import type { EvidencePackSignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { StatusPill } from "@/components/primitives/StatusPill";
import { Tag } from "@/components/primitives/Tag";
import { MODE_LABEL } from "@/lib/verdict";

interface SignalListProps {
  signals: EvidencePackSignal[];
}

/** Order signals so the underwriter sees flagged/errored items first, then valid-clean, then pending. */
function severityRank(s: EvidencePackSignal): number {
  if (s.status === "ERROR") return 0;
  if (s.status === "VALID" && (s.suspicion ?? 0) > 0) return 1;
  if (s.status === "VALID") return 2;
  return 3; // NOT_EVALUATED / pending
}

function humanName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Per-signal list — the explainability core (CLAUDE.md §9). Each row shows the signal's status
 * (Valid / Pending / Error), its PRODUCING-MODE tag (the mode-tagging invariant made visible),
 * its layer, its weight/suspicion contribution, and the analyzer's own reason string.
 *
 * Every value is from evidence_pack.signals — nothing computed or invented here.
 */
export function SignalList({ signals }: SignalListProps) {
  const ordered = [...signals].sort((a, b) => severityRank(a) - severityRank(b));

  return (
    <Panel
      title="Per-signal results"
      aside={`${signals.length} signal${signals.length === 1 ? "" : "s"}`}
    >
      {ordered.length === 0 ? (
        <p className="text-sm text-slate-400">No signals reported for this intake.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {ordered.map((s) => {
            const flagged = s.status === "VALID" && (s.suspicion ?? 0) > 0;
            return (
              <li key={s.name} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={s.status} />
                  <span className="text-sm font-medium text-slate-100">{humanName(s.name)}</span>
                  <Tag tone="accent" title="The medium this signal was physically produced on">
                    mode: {MODE_LABEL[s.producing_mode] ?? s.producing_mode}
                  </Tag>
                  <Tag title="Verification layer (1 capture · 2 identity · 3 forensics · 4 challenge · 5 risk)">
                    layer {s.layer}
                  </Tag>
                  {s.status === "VALID" && (
                    <Tag
                      tone={flagged ? "warn" : "subtle"}
                      className="ml-auto"
                      title="Suspicion (0 clean → 1 maximally suspicious) and the signal's scoring weight"
                    >
                      suspicion {(s.suspicion ?? 0).toFixed(2)} · weight {s.weight.toFixed(2)}
                    </Tag>
                  )}
                </div>
                {s.reason && <p className="pl-1 text-sm text-slate-400">{s.reason}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
