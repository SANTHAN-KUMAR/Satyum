/** The console masthead — product identity + the security framing (CLAUDE.md §9 "fintech security console"). */
export function AppHeader() {
  return (
    <header className="border-b border-hairline bg-surface/60 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-4 sm:px-6">
        <div
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/40 bg-accent/10 text-accent"
          aria-hidden="true"
        >
          <span className="text-lg font-bold">स</span>
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold tracking-tight text-slate-100">
            Satyum · Underwriter Evidence Console
          </h1>
          <p className="truncate text-xs text-slate-500">
            Real-time document-integrity verification · Canara Bank
          </p>
        </div>
        <span className="ml-auto hidden rounded-full border border-hairline bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-slate-400 sm:inline">
          Provenance-first · fail-closed
        </span>
      </div>
    </header>
  );
}
