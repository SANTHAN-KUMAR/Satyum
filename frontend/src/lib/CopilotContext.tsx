import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { EvidencePack } from "@/api/types";

/** One document's evidence, labeled for the copilot's tools (a filename, or a doc type). */
export interface CopilotDocument {
  label: string;
  pack: EvidencePack;
}

/**
 * What the global Copilot currently reasons about. Exactly one of two shapes:
 *   - "document": a single document under review (Console) — one evidence pack, one narrative.
 *   - "case": every document accumulated in an application case so far (Case page) — the copilot can
 *     answer a question about ANY of them, not just the most recently added one, because the case
 *     page fetches the full set fresh from the backend (GET /api/cases/{id}/evidence) every time a
 *     document is added, rather than only remembering the single latest evidence pack in memory.
 * `null` means nothing real has been produced yet — the drawer says so honestly (CLAUDE.md §9).
 */
export type CopilotScope =
  | { kind: "document"; label: string; pack: EvidencePack }
  | { kind: "case"; caseId: string; documents: CopilotDocument[] }
  | null;

/** A stable identity for a scope — changes exactly when what the copilot should be discussing changes
 * (a different document, a different case, or the case's document set growing), so the panel knows
 * precisely when to drop its narrative/chat state and never carry old answers into new content.
 *
 * Keyed on each pack's `session_id`, NOT the filename: re-verifying the SAME file (e.g. after a fix, or
 * just re-running it) produces a genuinely new analysis with a new session_id, and must be treated as a
 * new scope — otherwise the narrative/chat effects would never re-fire and stale results from the
 * earlier run could keep showing (this was the actual root cause of a stale-narrative report: the
 * document was re-verified, but nothing downstream noticed the analysis had changed). */
export function copilotScopeKey(scope: CopilotScope): string {
  if (!scope) return "none";
  if (scope.kind === "document") return `document:${scope.pack.session_id ?? scope.label}`;
  return `case:${scope.caseId}:${scope.documents.map((d) => `${d.label}#${d.pack.session_id ?? ""}`).join(",")}`;
}

interface CopilotContextValue {
  scope: CopilotScope;
  /** Register a single document (e.g. a Console verification) as the copilot's active context. */
  setDocumentContext: (pack: EvidencePack, label: string) => void;
  /** Register an application case's FULL accumulated document set — call this every time the case's
   * documents change (case opened, or a document added), not just once, so the copilot never falls
   * behind what's actually in the case. */
  setCaseContext: (caseId: string, documents: CopilotDocument[]) => void;
  clearCopilotContext: () => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}

const Ctx = createContext<CopilotContextValue | null>(null);

/**
 * Holds what the global Copilot drawer currently reasons about, independent of route. Whichever page
 * most recently produced a real result — a single-document verify, or an application case's document
 * set — registers it here; the drawer then stays available, and keeps that context, no matter which
 * page the underwriter navigates to next (console / case / consortium / master model). There is no
 * synthetic evidence pack for Consortium/Master Model: they have no such object in the backend
 * contract, so the drawer honestly shows "nothing to analyze yet" there until a real one exists
 * (CLAUDE.md §9 — no fabricated data).
 */
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<CopilotScope>(null);
  const [open, setOpen] = useState(false);

  const setDocumentContext = useCallback((pack: EvidencePack, label: string) => {
    setScope({ kind: "document", label, pack });
  }, []);
  const setCaseContext = useCallback((caseId: string, documents: CopilotDocument[]) => {
    setScope({ kind: "case", caseId, documents });
  }, []);
  const clearCopilotContext = useCallback(() => {
    setScope(null);
  }, []);

  const value = useMemo(
    () => ({ scope, setDocumentContext, setCaseContext, clearCopilotContext, open, setOpen }),
    [scope, setDocumentContext, setCaseContext, clearCopilotContext, open],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCopilotContext(): CopilotContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCopilotContext must be used within a CopilotProvider");
  return ctx;
}
