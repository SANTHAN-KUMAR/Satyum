import { Bot, X } from "lucide-react";
import { useCopilotContext } from "@/lib/CopilotContext";
import { CopilotPanel } from "../Console/CopilotPanel";
import { cn } from "@/lib/cn";

/**
 * The omnipresent Copilot — a floating toggle + slide-in drawer mounted once in AppShell, so it
 * survives navigation between Console / Case / Consortium / Master model instead of being torn down
 * and rebuilt per page (the "state gets destroyed" problem). It always shows the LAST real evidence
 * pack registered via CopilotContext, regardless of which page put it there; on a page with nothing
 * registered yet it says so honestly rather than faking a conversation with no data behind it.
 */
export function GlobalCopilotDrawer() {
  const { evidencePack, sourceLabel, open, setOpen } = useCopilotContext();

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls="global-copilot-drawer"
        className={cn(
          "fixed bottom-5 right-5 z-40 flex h-13 items-center gap-2 rounded-full px-4 py-3 text-sm font-semibold text-white shadow-lift transition",
          open ? "bg-ink" : "gradient-accent hover:brightness-105",
        )}
      >
        {open ? <X size={18} aria-hidden="true" /> : <Bot size={18} aria-hidden="true" />}
        {open ? "Close" : "Copilot"}
        {!open && evidencePack && <span className="h-1.5 w-1.5 rounded-full bg-white/90" aria-hidden="true" />}
      </button>

      {open && (
        <div
          id="global-copilot-drawer"
          role="complementary"
          aria-label="AI underwriter copilot"
          className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-hairline bg-surface shadow-lift sm:inset-y-4 sm:right-4 sm:rounded-2xl"
        >
          <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-slate-100">Underwriter copilot</p>
              <p className="text-xs text-slate-500">
                {sourceLabel ? `Analyzing ${sourceLabel}` : "No document in scope"}
              </p>
            </div>
            <button onClick={() => setOpen(false)} className="btn-ghost !px-2 !py-1.5" aria-label="Close copilot">
              <X size={16} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {evidencePack ? (
              <CopilotPanel evidencePack={evidencePack} />
            ) : (
              <div className="rounded-xl border border-dashed border-hairline p-5 text-center text-sm text-slate-500">
                Nothing to analyze yet. Verify a document or add one to a case — the copilot activates
                on the real evidence pack it produces and stays available as you move around the app.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
