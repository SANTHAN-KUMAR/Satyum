import { ShieldCheck } from "lucide-react";
import { COPY } from "@/lib/copy";

/** The console masthead — clean, professional, focused on trust. */
export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-hairline bg-canvas/85 backdrop-blur">
      <div className="flex h-14 items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent"
            aria-hidden="true"
          >
            <ShieldCheck size={18} strokeWidth={2} />
          </div>
          <div className="flex items-baseline gap-2">
            <h1 className="text-[15px] font-semibold tracking-tight text-text-primary">
              {COPY.BRAND_NAME}
            </h1>
            <span className="text-xs font-medium text-text-tertiary">
              {COPY.BANK_NAME}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
