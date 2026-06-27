import type { Verdict } from "@/api/types";
import { VERDICT_THEME } from "@/lib/verdict";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

interface RecommendedActionProps {
  action: string;
  verdict: Verdict;
}

/** The recommended next step for the underwriter, verbatim from evidence_pack.recommended_action. */
export function RecommendedAction({ action, verdict }: RecommendedActionProps) {
  const t = VERDICT_THEME[verdict];
  return (
    <Panel title="Recommended action">
      <div className={cn("rounded-lg border-l-4 bg-surface-2 px-4 py-3", `border-l-current ${t.text}`)}>
        <p className="text-sm leading-relaxed text-slate-200">{action}</p>
      </div>
    </Panel>
  );
}
