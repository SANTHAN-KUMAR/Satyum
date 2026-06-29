import type { Verdict } from "@/api/types";
import { VERDICT_THEME } from "@/lib/verdict";
import { cn } from "@/lib/cn";
import { Tag } from "@/components/primitives/Tag";

interface VerdictBannerProps {
  verdict: Verdict;
  /** When the backend degraded the outcome to the safe side (CLAUDE.md §4 fail-closed). */
  failClosed: boolean;
}

/**
 * The hero verdict state — unmistakable (CLAUDE.md §9). Conveyed by glyph + word + colour together,
 * not colour alone, and announced to assistive tech. A fail-closed degradation is surfaced honestly
 * so an underwriter knows REVIEW came from an analyzer error / indeterminate aggregate, not a clean read.
 */
export function VerdictBanner({ verdict, failClosed }: VerdictBannerProps) {
  const t = VERDICT_THEME[verdict];
  return (
    <div
      role="status"
      aria-label={`Verdict: ${t.label}${failClosed ? ", fail-closed (degraded to the safe side)" : ""}`}
      className={cn(
        "flex items-center gap-4 rounded-xl border px-5 py-4 ring-1",
        t.bg,
        t.border,
        t.ring,
      )}
    >
      <span
        className={cn(
          "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border",
          t.bg,
          t.border,
          t.text,
        )}
        aria-hidden="true"
      >
        <t.Icon size={26} strokeWidth={2} />
      </span>
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Document integrity verdict
        </p>
        <p className={cn("text-2xl font-bold leading-tight", t.text)}>{t.label}</p>
      </div>
      {failClosed && (
        <Tag tone="warn" className="ml-auto" title="The pipeline degraded toward the safer outcome">
          fail-closed
        </Tag>
      )}
    </div>
  );
}
