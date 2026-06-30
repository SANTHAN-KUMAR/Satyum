import type { SignalStatus } from "@/api/types";
import { STATUS_THEME } from "@/lib/verdict";
import { cn } from "@/lib/cn";

interface StatusPillProps {
  status: SignalStatus;
  className?: string;
}

/**
 * A signal-status pill (VALID / Pending / Error). Status is conveyed by BOTH an icon AND a text
 * label — never colour alone (accessibility, CLAUDE.md §9). NOT_EVALUATED reads "Pending" so a
 * not-run check is visibly distinct from a pass (§3.4).
 */
export function StatusPill({ status, className }: StatusPillProps) {
  const t = STATUS_THEME[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold",
        t.bg,
        t.border,
        t.text,
        className,
      )}
    >
      <t.Icon size={13} strokeWidth={2.25} aria-hidden="true" />
      <span>{t.label}</span>
      <span className="sr-only"> — status {status}</span>
    </span>
  );
}
