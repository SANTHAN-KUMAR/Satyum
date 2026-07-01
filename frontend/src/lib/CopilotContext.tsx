import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { EvidencePack } from "@/api/types";

interface CopilotContextValue {
  evidencePack: EvidencePack | null;
  /** Human label for what's currently in scope (e.g. a filename), shown in the drawer header. */
  sourceLabel: string | null;
  setCopilotContext: (pack: EvidencePack, sourceLabel: string) => void;
  clearCopilotContext: () => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}

const Ctx = createContext<CopilotContextValue | null>(null);

/**
 * Holds the ONE evidence pack the global Copilot drawer currently reasons about, independent of route.
 * Whichever page most recently produced a real verification result (single-document verify, or a
 * document added to a case) registers it here; the drawer then stays available — and keeps that
 * context — no matter which page the underwriter navigates to next (console / case / consortium /
 * master model). There is no synthetic "case-level" or "global" evidence pack: Consortium and Master
 * Model have no such object in the backend contract, so the drawer honestly shows "nothing to analyze
 * yet" there until a real one exists (CLAUDE.md §9 — no fabricated data).
 */
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [evidencePack, setEvidencePack] = useState<EvidencePack | null>(null);
  const [sourceLabel, setSourceLabel] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const setCopilotContext = useCallback((pack: EvidencePack, label: string) => {
    setEvidencePack(pack);
    setSourceLabel(label);
  }, []);
  const clearCopilotContext = useCallback(() => {
    setEvidencePack(null);
    setSourceLabel(null);
  }, []);

  const value = useMemo(
    () => ({ evidencePack, sourceLabel, setCopilotContext, clearCopilotContext, open, setOpen }),
    [evidencePack, sourceLabel, setCopilotContext, clearCopilotContext, open],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCopilotContext(): CopilotContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCopilotContext must be used within a CopilotProvider");
  return ctx;
}
