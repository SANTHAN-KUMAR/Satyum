import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PanelProps {
  title?: string;
  /** Optional small element rendered at the right of the header (e.g. a count or tag). */
  aside?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
  /** Renders the panel header as the labelled region for assistive tech. */
  ariaLabel?: string;
}

/** A titled console panel — the repeating surface of the evidence console. */
export function Panel({ title, aside, className, bodyClassName, children, ariaLabel }: PanelProps) {
  return (
    <section className={cn("panel", className)} aria-label={ariaLabel ?? title}>
      {(title || aside) && (
        <header className="flex items-center justify-between gap-3 border-b border-hairline px-4 py-3">
          {title && <h2 className="panel-title">{title}</h2>}
          {aside && <div className="text-xs text-slate-400">{aside}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
