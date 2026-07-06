import { useEffect, useMemo, useState } from "react";
import { Loader2, MessageSquare, ShieldAlert, Cpu, Files } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getNarrative, askCopilot, NarrativeReport, CopilotMessage } from "../../api/interpretability";
import type { CopilotScope } from "@/lib/CopilotContext";
import type { EvidencePack } from "@/api/types";

interface CopilotPanelProps {
  /** Never null — GlobalCopilotDrawer only mounts this once a real scope exists. */
  scope: Exclude<CopilotScope, null>;
}

/**
 * The Underwriter Copilot's body: an auto-narrative (single-document scope only — a "case" has no one
 * verdict to narrate) plus interactive Q&A, scoped to whichever document(s) `scope` names.
 *
 * Two bugs this fixes (both were real, observed in production):
 *   1. A slow in-flight narrative fetch for a PREVIOUS scope could resolve AFTER a newer scope's fetch
 *      had already completed, overwriting the correct narrative with stale text — a classic
 *      out-of-order-response race. Guarded here with a per-effect `cancelled` flag.
 *   2. `chatHistory` was never reset when the scope changed, so switching documents (or from a
 *      document to a case) carried an old Q&A transcript into a new session. Reset in an effect keyed
 *      on `scope` itself (see below).
 */
export function CopilotPanel({ scope }: CopilotPanelProps) {
  const caseDocuments = useMemo<Record<string, EvidencePack>>(() => {
    if (scope.kind === "document") return { [scope.label]: scope.pack };
    return Object.fromEntries(scope.documents.map((d) => [d.label, d.pack]));
  }, [scope]);

  const [narrative, setNarrative] = useState<NarrativeReport | null>(null);
  const [loadingNarrative, setLoadingNarrative] = useState(scope.kind === "document");

  const [chatHistory, setChatHistory] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);

  // Reset every piece of per-scope state the instant the scope changes — before any fetch resolves —
  // so stale narrative/chat text can never linger even for a moment on new content. Depending on
  // `scope` itself (not just its key) is correct here: the context only ever replaces this object via
  // setDocumentContext/setCaseContext, i.e. exactly when there is genuinely new content in scope.
  useEffect(() => {
    setChatHistory([]);
    setInput("");
    setNarrative(null);
    setLoadingNarrative(scope.kind === "document");
  }, [scope]);

  useEffect(() => {
    if (scope.kind !== "document") return; // no single verdict to narrate for a whole case
    let cancelled = false;
    setLoadingNarrative(true);
    getNarrative(scope.pack)
      .then((report) => {
        if (!cancelled) setNarrative(report);
      })
      .catch((err) => {
        if (!cancelled) console.error("Failed to load narrative", err);
      })
      .finally(() => {
        if (!cancelled) setLoadingNarrative(false);
      });
    return () => {
      cancelled = true; // a response for the scope we've since moved on from is ignored, never applied
    };
  }, [scope]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || asking) return;

    const userMsg: CopilotMessage = { role: "user", content: input };
    setChatHistory((prev) => [...prev, userMsg]);
    setInput("");
    setAsking(true);

    try {
      const response = await askCopilot(caseDocuments, userMsg.content, chatHistory);
      const assistantMsg: CopilotMessage = { role: "assistant", content: response.response };
      setChatHistory((prev) => [...prev, assistantMsg]);
    } catch (err) {
      console.error(err);
      setChatHistory((prev) => [...prev, { role: "assistant", content: "I encountered an error trying to process that." }]);
    } finally {
      setAsking(false);
    }
  };

  const chatDisabledReason = scope.kind === "document" && narrative?.is_fallback
    ? "Chat disabled (LLM unavailable)"
    : null;

  if (scope.kind === "document" && loadingNarrative) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl bg-ui-800 border border-ui-700/50">
        <Loader2 className="h-6 w-6 animate-spin text-ui-400" />
      </div>
    );
  }

  if (scope.kind === "document" && !narrative) {
    return null;
  }

  return (
    <div className="flex flex-col rounded-xl bg-ui-800 border border-ui-700/50 overflow-hidden mt-6">
      <div className="flex items-center gap-3 border-b border-ui-700/50 bg-ui-800/80 p-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-400 ring-1 ring-brand-500/20">
          <MessageSquare className="h-5 w-5" />
        </div>
        <div>
          <h3 className="font-medium text-ui-100">AI Underwriter Copilot</h3>
          <p className="text-sm text-ui-400">
            {scope.kind === "case"
              ? `Plain English Q&A across ${scope.documents.length} document(s) in this case`
              : "Plain English summary & Q&A"}
          </p>
        </div>
      </div>

      {scope.kind === "document" && narrative && (
        <div className="p-6 space-y-4 border-b border-ui-700/50">
          {narrative.is_fallback && (
            <div className="flex items-start gap-3 rounded-lg bg-orange-500/10 border border-orange-500/20 p-3 text-orange-200 text-sm">
              <ShieldAlert className="h-5 w-5 shrink-0 mt-0.5 text-orange-400" />
              <p>LLM unavailable. Showing deterministic fallback summary.</p>
            </div>
          )}

          <p className="text-ui-200 leading-relaxed">{narrative.summary_paragraph}</p>
          <p className="text-ui-200 leading-relaxed">{narrative.findings_paragraph}</p>

          <div className="bg-ui-900 rounded-lg p-4 border border-ui-700/50">
            <p className="text-ui-100 font-medium">{narrative.action_paragraph}</p>
          </div>
        </div>
      )}

      {scope.kind === "case" && (
        <div className="p-6 space-y-3 border-b border-ui-700/50">
          <div className="flex items-center gap-2 text-ui-300 text-sm">
            <Files className="h-4 w-4" />
            <span>{scope.documents.length} document(s) in this case — ask about any of them by name.</span>
          </div>
          <ul className="space-y-1.5">
            {scope.documents.map((d) => (
              <li key={d.label} className="flex items-center justify-between rounded-lg bg-ui-900 border border-ui-700/50 px-3 py-2 text-sm">
                <span className="text-ui-200">{d.label}</span>
                <span className="text-ui-400">{d.pack.verdict} · {d.pack.trust_score}/100</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="bg-ui-900 p-6 flex flex-col gap-4">
        <div className="flex flex-col gap-4 max-h-[300px] overflow-y-auto">
          {chatHistory.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-lg p-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-brand-500/20 text-brand-100 border border-brand-500/30"
                  : "bg-ui-800 text-ui-200 border border-ui-700"
              }`}>
                {msg.role === "user" ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <div className="prose prose-sm prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-ui-900 prose-pre:border-ui-700 prose-td:border-ui-700 prose-th:border-ui-700">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))}
          {asking && (
            <div className="flex justify-start">
              <div className="bg-ui-800 rounded-lg p-3 border border-ui-700 text-ui-400 flex items-center gap-2">
                <Cpu className="h-4 w-4 animate-pulse" />
                <span className="text-sm">Copilot is analyzing...</span>
              </div>
            </div>
          )}
        </div>

        <form onSubmit={handleAsk} className="relative mt-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={asking || !!chatDisabledReason}
            placeholder={chatDisabledReason ?? (scope.kind === "case" ? "Ask about any document in this case..." : "Ask about this document...")}
            className="w-full rounded-lg bg-ui-950 border border-ui-700 py-3 pl-4 pr-12 text-ui-100 placeholder:text-ui-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || asking || !!chatDisabledReason}
            className="absolute right-2 top-2 bottom-2 rounded-md bg-brand-500 px-3 text-white transition-colors hover:bg-brand-400 disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </div>
    </div>
  );
}
