import type { EvidencePackSignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { StatusPill } from "@/components/primitives/StatusPill";
import { Tag } from "@/components/primitives/Tag";
import { MODE_LABEL } from "@/lib/verdict";

interface LiveTierStatusProps {
  signals: EvidencePackSignal[];
  /** Whether the socket is open and we're actively streaming. */
  streaming: boolean;
}

/**
 * Live per-tier / per-signal status during a camera session, rendered ONLY from server-streamed
 * tier_status messages. Until the server sends any, this shows an honest "awaiting" state — never
 * placeholder pass/fail rows (CLAUDE.md §3.1/§9).
 */
export function LiveTierStatus({ signals, streaming }: LiveTierStatusProps) {
  return (
    <Panel title="Live signal status" aside={streaming ? "streaming" : "idle"}>
      {signals.length === 0 ? (
        <p className="text-sm text-slate-400">
          {streaming
            ? "Streaming frames — awaiting the server's per-tier evaluation…"
            : "No live signals yet. Start a session to stream frames to the verification pipeline."}
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
          {signals.map((s) => (
            <li key={s.name} className="flex flex-wrap items-center gap-2 py-2.5 first:pt-0 last:pb-0">
              <StatusPill status={s.status} />
              <span className="text-sm font-medium text-slate-100">{s.name.replace(/_/g, " ")}</span>
              <Tag tone="accent">mode: {MODE_LABEL[s.producing_mode] ?? s.producing_mode}</Tag>
              <Tag>layer {s.layer}</Tag>
              {s.reason && <span className="w-full pl-1 text-xs text-slate-500">{s.reason}</span>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
