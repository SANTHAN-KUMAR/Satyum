import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface TagProps {
  children: ReactNode;
  /** Subtle by default; `accent` for the producing-mode / tier emphasis. */
  tone?: "subtle" | "accent" | "warn";
  title?: string;
  className?: string;
}

/** A small inline metadata tag (producing-mode, layer, method, etc.). */
export function Tag({ children, tone = "subtle", title, className }: TagProps) {
  const tones: Record<NonNullable<TagProps["tone"]>, string> = {
    subtle: "border-hairline bg-surface-muted text-text-secondary",
    accent: "border-accent/40 bg-accent/10 text-accent",
    warn: "border-verdict-review/40 bg-verdict-review-soft text-verdict-review",
  };
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
