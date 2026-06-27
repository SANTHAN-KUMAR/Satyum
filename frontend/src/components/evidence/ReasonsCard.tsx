import { Panel } from "@/components/primitives/Panel";

interface ReasonsCardProps {
  reasons: string[];
}

/**
 * The arithmetic / tamper-evidence reasons — the human-readable "why" the backend composed
 * (provenance result, each flagged signal's reason, fail-closed errors). Rendered verbatim from
 * evidence_pack.reasons; nothing is synthesised client-side.
 */
export function ReasonsCard({ reasons }: ReasonsCardProps) {
  return (
    <Panel title="Why — evidence & reasons" aside={`${reasons.length}`}>
      <ol className="space-y-2">
        {reasons.map((reason, i) => (
          <li key={`${i}-${reason}`} className="flex gap-2.5 text-sm text-slate-300">
            <span
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface-2 text-[11px] font-semibold text-slate-400"
              aria-hidden="true"
            >
              {i + 1}
            </span>
            <span>{reason}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
