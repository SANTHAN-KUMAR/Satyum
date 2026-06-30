import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PanelProps {
  title?: string;
  /** Optional leading icon in the header (lucide), reinforcing the section at a glance. */
  icon?: LucideIcon;
  /** Optional small element rendered at the right of the header (e.g. a count or tag). */
  aside?: ReactNode;
  /** `muted` recedes the panel below the evidence (used for metadata/secondary sections). */
  variant?: "default" | "muted";
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
  /** Renders the panel header as the labelled region for assistive tech. */
  ariaLabel?: string;
}

/** A titled console panel — the repeating surface of the evidence console. */
export function Panel({
  title,
  icon: Icon,
  aside,
  variant = "default",
  className,
  bodyClassName,
  children,
  ariaLabel,
}: PanelProps) {
  return (
    <section
      className={cn(variant === "muted" ? "panel-muted" : "panel", className)}
      aria-label={ariaLabel ?? title}
    >
      {(title || aside) && (
        <header className="flex items-center justify-between gap-3 border-b border-hairline/70 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            {Icon && <Icon size={15} className="shrink-0 text-slate-500" aria-hidden="true" />}
            {title && <h2 className="panel-title">{title}</h2>}
          </div>
          {aside && <div className="shrink-0 text-xs text-slate-400">{aside}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
