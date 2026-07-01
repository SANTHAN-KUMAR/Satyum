import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export interface EvidenceTabDef {
  id: string;
  label: string;
  icon: LucideIcon;
}

interface EvidenceTabsProps {
  tabs: EvidenceTabDef[];
  active: string;
  onChange: (id: string) => void;
}

/**
 * Section switcher for the Underwriter Evidence Console (CLAUDE.md §9). Replaces the old "every section,
 * always, in one column" layout: only the active tab's evidence renders, so the console reads as a tool
 * to navigate rather than a report to scroll. Tabs that would have nothing to show are never passed in
 * (see EvidenceConsole), so there is no empty/fabricated tab state.
 */
export function EvidenceTabs({ tabs, active, onChange }: EvidenceTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Evidence sections"
      className="flex w-full gap-1 overflow-x-auto rounded-lg border border-hairline bg-surface-muted p-1"
      onKeyDown={(e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const idx = tabs.findIndex((t) => t.id === active);
        const dir = e.key === "ArrowRight" ? 1 : -1;
        const next = (idx + dir + tabs.length) % tabs.length;
        onChange(tabs[next]!.id);
      }}
    >
      {tabs.map((t) => {
        const isActive = t.id === active;
        return (
          <button
            key={t.id}
            role="tab"
            id={`evidence-tab-${t.id}`}
            aria-selected={isActive}
            aria-controls={`evidence-panel-${t.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-surface text-text-primary shadow-card"
                : "text-text-tertiary hover:bg-surface-hover hover:text-text-secondary",
            )}
          >
            <t.icon size={15} aria-hidden="true" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
