import { useState, useEffect } from "react";
import { Loader2, MessageSquare, ShieldAlert, Cpu } from "lucide-react";
import { getNarrative, askCopilot, NarrativeReport, CopilotMessage } from "../../api/interpretability";

export function CopilotPanel({ evidencePack }: { evidencePack: any }) {
  const [narrative, setNarrative] = useState<NarrativeReport | null>(null);
  const [loadingNarrative, setLoadingNarrative] = useState(true);
  
  const [chatHistory, setChatHistory] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!evidencePack) return;
    setLoadingNarrative(true);
    getNarrative(evidencePack)
      .then(setNarrative)
      .catch((err) => console.error("Failed to load narrative", err))
      .finally(() => setLoadingNarrative(false));
  }, [evidencePack]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || asking) return;

    const userMsg: CopilotMessage = { role: "user", content: input };
    setChatHistory((prev) => [...prev, userMsg]);
    setInput("");
    setAsking(true);

    try {
      const response = await askCopilot(evidencePack, userMsg.content, chatHistory);
      const assistantMsg: CopilotMessage = { role: "assistant", content: response.response };
      setChatHistory((prev) => [...prev, assistantMsg]);
    } catch (err) {
      console.error(err);
      setChatHistory((prev) => [...prev, { role: "assistant", content: "I encountered an error trying to process that." }]);
    } finally {
      setAsking(false);
    }
  };

  if (loadingNarrative) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl bg-ui-800 border border-ui-700/50">
        <Loader2 className="h-6 w-6 animate-spin text-ui-400" />
      </div>
    );
  }

  if (!narrative) {
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
          <p className="text-sm text-ui-400">Plain English summary & Q&A</p>
        </div>
      </div>

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

      <div className="bg-ui-900 p-6 flex flex-col gap-4">
        <div className="flex flex-col gap-4 max-h-[300px] overflow-y-auto">
          {chatHistory.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-lg p-3 text-sm leading-relaxed ${
                msg.role === "user" 
                  ? "bg-brand-500/20 text-brand-100 border border-brand-500/30" 
                  : "bg-ui-800 text-ui-200 border border-ui-700"
              }`}>
                {msg.content}
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
            disabled={asking || narrative.is_fallback}
            placeholder={narrative.is_fallback ? "Chat disabled (LLM unavailable)" : "Ask about this document..."}
            className="w-full rounded-lg bg-ui-950 border border-ui-700 py-3 pl-4 pr-12 text-ui-100 placeholder:text-ui-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
          />
          <button 
            type="submit" 
            disabled={!input.trim() || asking || narrative.is_fallback}
            className="absolute right-2 top-2 bottom-2 rounded-md bg-brand-500 px-3 text-white transition-colors hover:bg-brand-400 disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </div>
    </div>
  );
}
