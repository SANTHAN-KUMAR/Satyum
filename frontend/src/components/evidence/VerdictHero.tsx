import { ArrowRight, ShieldAlert } from "lucide-react";
import type { TrustScore } from "@/api/types";
import { TIER_LABEL, VERDICT_THEME } from "@/lib/verdict";
import { cn } from "@/lib/cn";
import { TrustGauge } from "./TrustGauge";

interface VerdictHeroProps {
  trust: TrustScore;
}

/**
 * The explainability HERO (CLAUDE.md §9). The single most important fact — APPROVE / REVIEW / REJECT
 * + the 0–100 trust score — dominates the console: large, verdict-tinted, and unmistakable across a
 * room or on a projector. It folds in the tier reached and the recommended next action so an
 * underwriter's 5-second scan ("approve or not, and what do I do") is answered before anything else.
 * Every value is read from the backend TrustScore — nothing is fabricated (§9).
 */
export function VerdictHero({ trust }: VerdictHeroProps) {
  const t = VERDICT_THEME[trust.verdict];
  const pack = trust.evidence_pack;
  const tierLabel = TIER_LABEL[trust.tier_reached] ?? trust.tier_reached;

  return (
    <section
      role="status"
      aria-label={`Verdict: ${t.label}. Trust score ${Math.round(trust.trust_score)} of 100.${
        trust.fail_closed ? " Fail-closed: degraded to the safe side." : ""
      }`}
      className={cn(
        "relative overflow-hidden rounded-2xl border shadow-xl shadow-black/40",
        t.border,
      )}
      // Verdict-tinted gradient over the surface — dynamic colour, so set inline (CLAUDE.md §9: the
      // colour still always rides alongside the icon + word, never colour alone).
      style={{
        background: `linear-gradient(135deg, ${t.stroke}26, ${t.stroke}08 38%, transparent 72%), #111a2c`,
      }}
    >
      {/* Strong verdict accent bar so rejection reads instantly at the edge of vision. */}
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5" style={{ backgroundColor: t.stroke }} />

      <div className="grid items-center gap-6 px-6 py-6 sm:px-8 lg:grid-cols-[1.4fr_auto]">
        {/* Left: the verdict + action. */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="eyebrow">Document integrity verdict</p>
            {trust.fail_closed && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-verdict-review/40 bg-verdict-review-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-verdict-review"
                title="The pipeline degraded toward the safer outcome (an analyzer errored or the aggregate was indeterminate)."
              >
                <ShieldAlert size={11} aria-hidden="true" /> fail-closed
              </span>
            )}
          </div>

          <div className="mt-2.5 flex items-center gap-4">
            <span
              className={cn(
                "flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border",
                t.bg,
                t.border,
              )}
              aria-hidden="true"
            >
              <t.Icon size={38} strokeWidth={2} className={t.text} />
            </span>
            <div className="min-w-0">
              <p className={cn("text-4xl font-extrabold leading-none tracking-tight sm:text-5xl", t.text)}>
                {t.label}
              </p>
              <p className="mt-2 text-sm font-medium text-slate-400">{tierLabel}</p>
            </div>
          </div>

          {/* Recommended action — the "what to do", verbatim from the backend. */}
          <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-hairline bg-canvas/40 px-4 py-3">
            <ArrowRight size={16} className={cn("mt-0.5 shrink-0", t.text)} aria-hidden="true" />
            <div className="min-w-0">
              <p className="eyebrow mb-0.5">Recommended action</p>
              <p className="text-sm leading-relaxed text-slate-200">{pack.recommended_action}</p>
            </div>
          </div>
        </div>

        {/* Right: the trust gauge. */}
        <div className="justify-self-center lg:justify-self-end">
          <TrustGauge score={trust.trust_score} verdict={trust.verdict} />
        </div>
      </div>
    </section>
  );
}
