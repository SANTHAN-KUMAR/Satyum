import { Clock } from "lucide-react";
import type { PendingSignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { Tag } from "@/components/primitives/Tag";

interface PendingListProps {
  pending: PendingSignal[];
}

/**
 * The not-evaluated / pending list (CLAUDE.md §3.4, §9): honestly-gated checks that did NOT run and
 * are excluded from the score — shown distinct from pass/fail so a not-run check is never mistaken
 * for a green pass. Each carries the precise reason it was gated. From evidence_pack.pending_not_evaluated.
 */
export function PendingList({ pending }: PendingListProps) {
  if (pending.length === 0) {
    return (
      <Panel title="Not evaluated (pending)" icon={Clock} aside="0">
        <p className="text-sm text-slate-400">
          Every applicable check was evaluated — nothing gated for this intake.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title="Not evaluated (pending)" icon={Clock} aside={`${pending.length} gated`}>
      <ul className="space-y-2.5">
        {pending.map((p) => (
          <li
            key={p.name}
            className="flex flex-col gap-1 rounded-lg border border-verdict-pending/30 bg-verdict-pending-soft px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <Tag>pending</Tag>
              <span className="text-sm font-medium text-slate-200">
                {p.name.replace(/_/g, " ")}
              </span>
            </div>
            <p className="text-sm text-slate-400">{p.reason}</p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
