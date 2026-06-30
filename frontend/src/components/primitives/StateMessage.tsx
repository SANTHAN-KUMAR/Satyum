import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "error" | "info" | "loading";

interface StateMessageProps {
  tone?: Tone;
  title: string;
  detail?: ReactNode;
  /** Optional action (e.g. a retry button). */
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

/**
 * The standard "designed empty/loading/error state" surface (CLAUDE.md §9: "every state designed").
 * Used for loading, error, no-camera, permission-denied, unreachable-backend, etc. — never a raw
 * browser error.
 */
export function StateMessage({ tone = "neutral", title, detail, action, icon, className }: StateMessageProps) {
  const tones: Record<Tone, string> = {
    neutral: "border-hairline text-text-secondary",
    error: "border-verdict-rejected/40 text-verdict-rejected",
    info: "border-accent/30 text-accent",
    loading: "border-hairline text-text-secondary",
  };
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "loading" ? "polite" : undefined}
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed bg-surface/40 px-6 py-10 text-center",
        tones[tone],
        className,
      )}
    >
      {tone === "loading" ? (
        <span
          className="h-6 w-6 animate-spin rounded-full border-2 border-hairline-strong border-t-accent"
          aria-hidden="true"
        />
      ) : (
        icon && <div aria-hidden="true">{icon}</div>
      )}
      <div className="space-y-1">
        <p className="text-sm font-semibold text-text-primary">{title}</p>
        {detail && <div className="mx-auto max-w-md text-sm text-text-secondary">{detail}</div>}
      </div>
      {action}
    </div>
  );
}
