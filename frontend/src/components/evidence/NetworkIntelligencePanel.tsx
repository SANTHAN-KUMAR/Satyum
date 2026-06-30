import type { NetworkIntelligenceFinding } from "@/api/types";

/**
 * The underwriter case-console network-intelligence panel (PROPOSAL-001 §8.4). Renders the Layer-3
 * advisory findings attached to THIS case — clearly labelled a FINDING, not a verdict. It never
 * entered the deterministic score (shown via the deterministic sub-score) and never auto-declines.
 * Renders nothing when the network was silent (fail-open).
 */
export function NetworkIntelligencePanel({
  findings,
  deterministicSubscore,
  trustScore,
}: {
  findings: NetworkIntelligenceFinding[];
  deterministicSubscore: number | null;
  trustScore: number;
}) {
  if (!findings || findings.length === 0) return null;

  return (
    <section className="glass gradient-ring rounded-2xl p-5" aria-label="Network intelligence">
      <div className="mb-3 flex items-center gap-2">
        <span aria-hidden className="gradient-text font-bold">ⓘ</span>
        <h3 className="gradient-text text-sm font-semibold uppercase tracking-wider">
          Network intelligence · finding — not a verdict
        </h3>
      </div>

      <ul className="space-y-3">
        {findings.map((f, i) => (
          <li key={i} className="rounded-xl border border-hairline bg-surface p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="rounded-full bg-saffron-soft px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-saffron-deep">
                {f.source.replace(/_/g, " ")}
              </span>
              <span className="text-xs text-slate-500 tnum">confidence {f.confidence.toFixed(2)}</span>
            </div>
            <p className="mt-2 text-sm text-slate-300">{f.explanation}</p>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-xs text-slate-500">
        This intelligence can only raise the case for a human. The deterministic score
        {deterministicSubscore != null && (
          <>
            {" "}
            (<span className="tnum font-medium text-slate-300">{deterministicSubscore}</span>) is unchanged
          </>
        )}
        {deterministicSubscore == null && <> ({<span className="tnum">{trustScore}</span>}) is unchanged</>}; it never
        auto-declines and never clears a document.
      </p>
    </section>
  );
}
