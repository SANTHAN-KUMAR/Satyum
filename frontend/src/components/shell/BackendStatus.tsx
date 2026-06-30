import { useEffect, useState } from "react";
import { getHealth } from "@/api/client";

/**
 * A live indicator of whether the backend is reachable. Polls /api/health. This is the answer to
 * "I don't see the backend running" — if it's red, the verification calls cannot work; start the
 * backend (see TESTING.md / start-dev.ps1).
 */
export function BackendStatus({ compact = false }: { compact?: boolean }) {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    const ping = async () => {
      try {
        await getHealth();
        if (active) setOnline(true);
      } catch {
        if (active) setOnline(false);
      }
    };
    ping();
    const id = setInterval(ping, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const dot =
    online === null ? "bg-slate-400" : online ? "bg-india-green" : "bg-verdict-rejected";
  const label =
    online === null ? "Checking backend…" : online ? "Backend connected" : "Backend offline — start it";

  if (compact) {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-xs text-slate-400"
        title={online ? "The backend is reachable." : "Start the backend (port 8000) — see TESTING.md."}
      >
        <span className={`h-2 w-2 rounded-full ${dot} ${online ? "animate-pulse" : ""}`} aria-hidden />
        {label}
      </span>
    );
  }

  return (
    <div
      className={
        "flex items-center gap-2 rounded-xl border px-3 py-2 text-xs " +
        (online === false
          ? "border-verdict-rejected/30 bg-verdict-rejected-soft text-verdict-rejected"
          : "border-hairline bg-surface-2/60 text-slate-400")
      }
    >
      <span className={`h-2.5 w-2.5 rounded-full ${dot} ${online ? "animate-pulse" : ""}`} aria-hidden />
      <span className="font-medium">{label}</span>
      {online === false && (
        <span className="ml-auto text-[11px] text-slate-500">port 8000</span>
      )}
    </div>
  );
}
