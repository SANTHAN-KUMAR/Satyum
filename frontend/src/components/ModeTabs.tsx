import { Camera, FileUp, Files, LayoutPanelTop } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { COPY } from "@/lib/copy";

export type IntakeTab = "upload" | "bundle" | "camera" | "sample";

interface ModeTabsProps {
  active: IntakeTab;
  onChange: (tab: IntakeTab) => void;
  className?: string;
}

const TABS: { id: IntakeTab; label: string; icon: LucideIcon }[] = [
  { id: "upload", label: COPY.TAB_DOCUMENT, icon: FileUp },
  { id: "bundle", label: COPY.TAB_BUNDLE, icon: Files },
  { id: "camera", label: COPY.TAB_CAMERA, icon: Camera },
  { id: "sample", label: COPY.TAB_SAMPLE, icon: LayoutPanelTop },
];

/** Accessible tablist for switching intake modes. Vertical on desktop, horizontal on mobile. */
export function ModeTabs({ active, onChange, className }: ModeTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Verification intake mode"
      className={cn("flex w-full gap-1 sm:flex-col", className)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        const idx = TABS.findIndex((t) => t.id === active);
        const dir = (e.key === "ArrowRight" || e.key === "ArrowDown") ? 1 : -1;
        const next = (idx + dir + TABS.length) % TABS.length;
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
              "flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium transition-colors sm:flex-none sm:justify-start",
              isActive
                ? "bg-surface-hover text-accent"
                : "text-text-secondary hover:bg-surface hover:text-text-primary",
            )}
          >
            <t.icon size={16} aria-hidden="true" />
            <span className="hidden sm:inline">{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}
