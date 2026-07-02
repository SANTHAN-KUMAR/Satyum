import { Bot, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { useCopilotContext } from "@/lib/CopilotContext";
import { CopilotPanel } from "../Console/CopilotPanel";
import { cn } from "@/lib/cn";

const PAGE_LABEL: Record<string, string> = {
  "/console": "Underwriter console",
  "/case": "Application case",
  "/consortium": "Consortium",
  "/model": "Master model",
};

/** True on pages that have no document-evidence-pack concept at all — the backend's
 * /api/interpret/narrative + /ask only ever reason over a single document's EvidencePack, so on
 * these pages the copilot is honestly showing PRIOR context, not this page's content. */
function pageHasNoEvidenceConcept(pathname: string): boolean {
  return pathname.startsWith("/consortium") || pathname.startsWith("/model");
}

/**
 * The omnipresent Copilot — a floating toggle + slide-in drawer mounted once in AppShell, so it
 * survives navigation between Console / Case / Consortium / Master model instead of being torn down
 * and rebuilt per page (the "state gets destroyed" problem). It always shows the LAST real evidence
 * pack registered via CopilotContext, regardless of which page put it there.
 *
 * The panel stays mounted at all times (visibility toggled with CSS, not conditional rendering) so
 * closing and reopening the drawer does NOT discard the loaded narrative or chat history and does NOT
 * re-fetch — CopilotPanel's own state only resets when the evidence pack itself changes. On a page with
 * no document-evidence-pack concept (Consortium, Master Model), a banner says so explicitly instead of
 * silently discussing a stale document as if it were this page's content — the backend has no way to
 * reason about ring/network data today, so faking that here would violate CLAUDE.md §9.
 */
export function GlobalCopilotDrawer() {
  const { evidencePack, sourceLabel, open, setOpen } = useCopilotContext();
  const { pathname } = useLocation();
  const pageLabel = PAGE_LABEL[pathname] ?? pathname;
  const offTopic = pageHasNoEvidenceConcept(pathname) && evidencePack != null;

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

      <div
        id="global-copilot-drawer"
        role="complementary"
        aria-label="AI underwriter copilot"
        aria-hidden={!open}
        className={cn(
          "fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-hairline bg-surface shadow-lift transition-transform duration-200 sm:inset-y-4 sm:right-4 sm:rounded-2xl",
          open ? "translate-x-0" : "pointer-events-none translate-x-full",
        )}
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

        {offTopic && (
          <div className="border-b border-hairline bg-verdict-review-soft px-4 py-2.5 text-xs text-verdict-review">
            You're on <strong>{pageLabel}</strong>, which has no document evidence pack of its own — the
            copilot below is still discussing the last document it analyzed ({sourceLabel}), not this
            page. Cross-bank/ring reasoning isn't wired into the copilot yet.
          </div>
        )}

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
    </>
  );
}
