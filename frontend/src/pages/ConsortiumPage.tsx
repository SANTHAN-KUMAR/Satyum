import { useState } from "react";
import { ApiError } from "@/api/client";
import {
  detectRings,
  queryRegistry,
  reportFraud,
  submitApplication,
  type RegistryMatch,
  type RingEvidence,
} from "@/api/federation";
import { RingGraph, RingGraphGhost } from "@/components/network/RingGraph";

/**
 * The Consortium simulator — HOW you test multi-bank pattern identification. Act as any member bank,
 * submit applications (as a ring member or an independent applicant), and watch the network surface
 * reuse and rings no single bank can see. Every action hits the real backend; identifiers are
 * tokenised server-side before they touch the graph.
 */

const BANKS = ["canara", "sbi", "hdfc", "icici", "union"];
const RING = { payout_account: "50100123456789", device: "DV-FP-AA11", employer: "COMPANY X PVT" };
const DEMO_PHASH = "f0e1d2c3b4a5968778695a4b3c2d1e0f0123456789abcdef0123456789abcdef";

interface LogEntry {
  bank: string;
  caseId: string;
  kind: "ring member" | "independent";
}

export function ConsortiumPage() {
  const [bank, setBank] = useState(BANKS[0]!);
  const [kind, setKind] = useState<"ring" | "unique">("ring");
  const [counter, setCounter] = useState(1);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [rings, setRings] = useState<RingEvidence[] | null>(null);
  const [match, setMatch] = useState<RegistryMatch | null>(null);
  const [reported, setReported] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  };

  const submitApp = () =>
    guard(async () => {
      const caseId = `${bank}:LN-${counter}`;
      const ids =
        kind === "ring"
          ? RING
          : { payout_account: `ACCT-${counter}-${bank}`, device: `DEV-${counter}-${bank}`, employer: `EMPLOYER-${counter}` };
      await submitApplication({ case_id: caseId, bank_id: bank, ...ids });
      setCounter((c) => c + 1);
      setLog((l) => [{ bank, caseId, kind: kind === "ring" ? "ring member" : "independent" }, ...l]);
      setRings(null);
    });

  const detect = () =>
    guard(async () => {
      const res = await detectRings();
      setRings(res.rings);
    });

  const report = () =>
    guard(async () => {
      await reportFraud({ threat_class: "forged_statement", label: `${bank}:fraud`, phash_hex: DEMO_PHASH, pan: "ABCPK1234L", bank_id: bank });
      setReported(true);
    });

  const query = () =>
    guard(async () => {
      const res = await queryRegistry({ phash_hex: DEMO_PHASH, pan: "ABCPK1234L" });
      setMatch(res.matched ? (res.matches[0] ?? null) : null);
    });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Consortium simulator</h1>
        <p className="text-sm text-slate-500">
          Play any member bank and submit applications. The network connects the tokenised dots —
          surfacing reuse and rings that no single bank can see alone.
        </p>
      </div>

      {/* bank picker */}
      <div className="flex flex-wrap gap-2">
        {BANKS.map((b) => (
          <button
            key={b}
            onClick={() => setBank(b)}
            className={
              "rounded-xl border px-4 py-2 text-sm font-medium capitalize transition " +
              (b === bank ? "border-navy bg-navy text-white" : "border-hairline bg-surface text-slate-400 hover:bg-surface-2")
            }
          >
            {b}
          </button>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* submit */}
        <section className="panel p-5">
          <h2 className="text-base font-semibold text-navy">Submit an application as {bank}</h2>
          <p className="mt-1 text-sm text-slate-400">Choose what kind of applicant this is.</p>
          <div className="mt-4 flex gap-2">
            <Toggle active={kind === "ring"} onClick={() => setKind("ring")}>
              Ring member (shares the fraud fingerprint)
            </Toggle>
            <Toggle active={kind === "unique"} onClick={() => setKind("unique")}>
              Independent applicant
            </Toggle>
          </div>
          <button onClick={submitApp} disabled={busy} className="btn-primary mt-4">
            Submit as {bank}
          </button>

          <div className="mt-5">
            <p className="panel-title mb-2">Network activity ({log.length})</p>
            <ul className="max-h-48 space-y-1 overflow-auto text-sm">
              {log.length === 0 && <li className="text-slate-500">No applications submitted yet.</li>}
              {log.map((e, i) => (
                <li key={i} className="flex items-center justify-between rounded-lg bg-surface-2/60 px-3 py-1.5">
                  <span className="font-mono text-xs text-slate-300">{e.caseId}</span>
                  <span className={"text-xs " + (e.kind === "ring member" ? "text-verdict-review" : "text-slate-500")}>
                    {e.kind}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* detect */}
        <section className="panel p-5">
          <h2 className="text-base font-semibold text-navy">Detect across the network</h2>
          <p className="mt-1 text-sm text-slate-400">
            Pool the tokenised links across all banks and surface coordinated rings.
          </p>
          <button onClick={detect} disabled={busy} className="btn-primary mt-4">
            Detect rings
          </button>
          {rings && rings.length > 0 && rings[0] && (
            <div className="mt-4">
              <RingGraph ring={rings[0]} />
              <p className="mt-3 rounded-xl border border-navy/20 bg-navy-soft/50 p-3 text-sm text-slate-300">
                {rings[0].explanation}
              </p>
            </div>
          )}
          {rings && rings.length === 0 && (
            <p className="mt-4 text-sm text-slate-400">
              No ring yet — submit at least 3 “ring member” applications across banks, then detect.
            </p>
          )}
          {!rings && (
            <div className="mt-4">
              <RingGraphGhost />
              <p className="mt-1 text-center text-xs text-slate-500">
                Illustrative — this is what a detected ring's shared-identifier graph looks like.
              </p>
            </div>
          )}
        </section>
      </div>

      {/* registry */}
      <section className="panel p-5">
        <h2 className="text-base font-semibold text-navy">Shared fraud registry</h2>
        <p className="mt-1 text-sm text-slate-400">
          Report a confirmed forgery as one bank, then check it from another — caught across institutions,
          with only hashes shared.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={report} disabled={busy} className="btn-ghost">
            Report a forgery as {bank}
          </button>
          <button onClick={query} disabled={busy || !reported} className="btn-primary">
            Check this fingerprint from {bank}
          </button>
        </div>
        {match && (
          <div className="mt-4 rounded-xl border border-navy/20 bg-navy-soft/50 p-4 text-sm text-slate-300">
            <b className="text-navy">Match.</b> Flagged at <b>{match.label}</b> · threat {match.threat_class} ·
            shared {match.matched_token_kinds.join(", ") || "fingerprint"} · seen at {match.banks_seen} bank(s).
          </div>
        )}
      </section>

      {error && <p className="text-sm text-verdict-rejected">⚠ {error}</p>}
    </div>
  );
}

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={
        "flex-1 rounded-xl border px-3 py-2 text-left text-sm transition " +
        (active ? "border-navy bg-navy-soft/60 font-medium text-navy" : "border-hairline bg-surface text-slate-400 hover:bg-surface-2")
      }
    >
      {children}
    </button>
  );
}
