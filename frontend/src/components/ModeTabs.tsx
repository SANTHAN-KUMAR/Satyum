import { Camera, FileUp, Files, LayoutPanelTop } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export type IntakeTab = "upload" | "bundle" | "camera" | "sample";

interface ModeTabsProps {
  active: IntakeTab;
  onChange: (tab: IntakeTab) => void;
}

const TABS: { id: IntakeTab; label: string; hint: string; icon: LucideIcon }[] = [
  { id: "upload", label: "File upload", hint: "Primary path · PDF / image", icon: FileUp },
  { id: "bundle", label: "Document bundle", hint: "Cross-document identity check", icon: Files },
  { id: "camera", label: "Live capture", hint: "Tier 3 · in-person", icon: Camera },
  { id: "sample", label: "Sample view", hint: "Offline layout preview", icon: LayoutPanelTop },
];

/** Accessible tablist for switching intake modes. Keyboard: arrow keys move, Enter/Space activate. */
export function ModeTabs({ active, onChange }: ModeTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Verification intake mode"
      className="inline-flex gap-1 rounded-lg border border-hairline bg-surface/60 p-1"
      onKeyDown={(e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const idx = TABS.findIndex((t) => t.id === active);
        const next = e.key === "ArrowRight" ? (idx + 1) % TABS.length : (idx - 1 + TABS.length) % TABS.length;
        onChange(TABS[next]!.id);
      }}
    >
      {TABS.map((t) => {
        const isActive = t.id === active;
        return (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={isActive}
            aria-controls={`panel-${t.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-accent/15 text-accent"
                : "text-slate-400 hover:bg-surface-2 hover:text-slate-200",
            )}
            title={t.hint}
          >
            <t.icon size={14} aria-hidden="true" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
