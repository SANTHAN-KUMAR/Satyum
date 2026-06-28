import type { SignalStatus } from "@/api/types";
import { STATUS_THEME } from "@/lib/verdict";
import { cn } from "@/lib/cn";

interface StatusPillProps {
  status: SignalStatus;
  className?: string;
}

/**
 * A signal-status pill (VALID / Pending / Error). Status is conveyed by BOTH a coloured dot AND a
 * text label — never colour alone (accessibility, CLAUDE.md §9). NOT_EVALUATED reads "Pending" so a
 * not-run check is visibly distinct from a pass (§3.4).
 */
export function StatusPill({ status, className }: StatusPillProps) {
  const t = STATUS_THEME[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
        t.bg,
        t.border,
        t.text,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", t.dot)} aria-hidden="true" />
      <span>{t.label}</span>
      <span className="sr-only"> — status {status}</span>
    </span>
  );
}
