import { Lock, ShieldCheck } from "lucide-react";

/** The console masthead — product identity + the security framing (CLAUDE.md §9 "fintech security console"). */
export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-hairline bg-canvas/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3.5 sm:px-6">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent/40 bg-gradient-to-br from-accent/25 to-accent/5 text-accent"
          aria-hidden="true"
        >
          <ShieldCheck size={20} strokeWidth={2} />
        </div>
        <div className="min-w-0">
          <h1 className="flex items-baseline gap-2 truncate text-[15px] font-bold tracking-tight text-slate-50">
            Satyum
            <span className="hidden text-xs font-normal text-slate-500 sm:inline">
              · Underwriter Evidence Console
            </span>
          </h1>
          <p className="truncate text-xs text-slate-500">
            Real-time document-integrity verification · Canara Bank
          </p>
        </div>
        <span className="ml-auto hidden items-center gap-1.5 rounded-full border border-hairline bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-slate-300 sm:inline-flex">
          <Lock size={11} aria-hidden="true" />
          Provenance-first · fail-closed
        </span>
      </div>
    </header>
  );
}
