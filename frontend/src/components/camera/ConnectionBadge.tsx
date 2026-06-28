import type { SocketState } from "@/hooks/useVerifysocket";
import { cn } from "@/lib/cn";

interface ConnectionBadgeProps {
  state: SocketState;
}

/**
 * Honest WebSocket connection state (CLAUDE.md §3.1/§9: "if the WS backend isn't ready it shows a
 * connection state honestly — never fake data"). "Unreachable" is a first-class, truthful state.
 */
const COPY: Record<SocketState, { label: string; dot: string; text: string }> = {
  idle: { label: "Not connected", dot: "bg-slate-500", text: "text-slate-400" },
  connecting: { label: "Connecting…", dot: "bg-amber-400 animate-pulse", text: "text-amber-300" },
  open: { label: "Connected · /ws/verify", dot: "bg-emerald-400", text: "text-emerald-300" },
  closed: { label: "Disconnected", dot: "bg-slate-500", text: "text-slate-400" },
  unreachable: {
    label: "Backend unreachable",
    dot: "bg-verdict-rejected",
    text: "text-verdict-rejected",
  },
};

export function ConnectionBadge({ state }: ConnectionBadgeProps) {
  const c = COPY[state];
  return (
    <span
      className={cn("inline-flex items-center gap-2 text-xs font-medium", c.text)}
      role="status"
      aria-live="polite"
    >
      <span className={cn("h-2 w-2 rounded-full", c.dot)} aria-hidden="true" />
      {c.label}
    </span>
  );
}
