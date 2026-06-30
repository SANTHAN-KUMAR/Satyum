import { useMemo } from "react";
import type { Verdict } from "@/api/types";
import { BANDS, SCORE_BANDS, VERDICT_THEME } from "@/lib/verdict";
import { useCountUp } from "@/hooks/useCountUp";

interface TrustGaugeProps {
  /** 0..100, from the backend. */
  score: number;
  verdict: Verdict;
}

// Geometry of the 240° semi-circular gauge.
const START_DEG = 150; // sweep start (bottom-left)
const SWEEP_DEG = 240; // total sweep
const RADIUS = 80;
const CENTER = 100;
const STROKE = 16;

function polar(valueDeg: number): { x: number; y: number } {
  const rad = (valueDeg * Math.PI) / 180;
  return { x: CENTER + RADIUS * Math.cos(rad), y: CENTER + RADIUS * Math.sin(rad) };
}

/** Build an SVG arc path between two scores (0..100) along the gauge sweep. */
function arcPath(fromScore: number, toScore: number): string {
  const a0 = START_DEG + (fromScore / 100) * SWEEP_DEG;
  const a1 = START_DEG + (toScore / 100) * SWEEP_DEG;
  const p0 = polar(a0);
  const p1 = polar(a1);
  const largeArc = a1 - a0 > 180 ? 1 : 0;
  return `M ${p0.x} ${p0.y} A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${p1.x} ${p1.y}`;
}

/**
 * Animated 0–100 trust gauge with the labelled threshold bands (Reject / Review / Approve) drawn as
 * the backing arc and the live score swept on top. The numeric value and band labels are accessible
 * (aria) and never colour-only. The score and verdict come straight from the backend.
 */
export function TrustGauge({ score, verdict }: TrustGaugeProps) {
  const animated = useCountUp(score);
  const theme = VERDICT_THEME[verdict];

  const bandSegments = useMemo(
    () => SCORE_BANDS.map((b) => ({ ...b, d: arcPath(b.from, b.to) })),
    [],
  );

  // Tick labels at the two thresholds.
  const ticks = useMemo(() => {
    const make = (s: number) => {
      const a = START_DEG + (s / 100) * SWEEP_DEG;
      const inner = (() => {
        const rad = (a * Math.PI) / 180;
        const r = RADIUS + STROKE / 2 + 6;
        return { x: CENTER + r * Math.cos(rad), y: CENTER + r * Math.sin(rad) };
      })();
      return { s, ...inner };
    };
    return [make(BANDS.reviewAt), make(BANDS.approveAt)];
  }, []);

  return (
    <div className="flex flex-col items-center">
      <svg
        viewBox="0 0 200 160"
        className="w-full max-w-[280px]"
        role="img"
        aria-label={`Trust score ${Math.round(score)} of 100, verdict ${theme.label}. Bands: reject below ${BANDS.reviewAt}, review ${BANDS.reviewAt} to ${BANDS.approveAt}, approve ${BANDS.approveAt} and above.`}
      >
        {/* Track */}
        <path
          d={arcPath(0, 100)}
          fill="none"
          stroke="#262626"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        {/* Labelled bands (muted) */}
        {bandSegments.map((b) => (
          <path
            key={b.label}
            d={b.d}
            fill="none"
            stroke={b.color}
            strokeOpacity={0.28}
            strokeWidth={STROKE}
          />
        ))}
        {/* Live value sweep (verdict-coloured) */}
        <path
          d={arcPath(0, Math.max(0.01, animated))}
          fill="none"
          stroke={theme.stroke}
          strokeWidth={STROKE}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${theme.stroke}88)` }}
        />
        {/* Threshold ticks */}
        {ticks.map((t) => (
          <text
            key={t.s}
            x={t.x}
            y={t.y}
            fill="#94a3b8"
            fontSize="8"
            textAnchor="middle"
            dominantBaseline="middle"
          >
            {t.s}
          </text>
        ))}
        {/* Numeric readout */}
        <text
          x={CENTER}
          y={CENTER + 4}
          textAnchor="middle"
          fontSize="34"
          fontWeight="700"
          fill="#f1f5f9"
        >
          {Math.round(animated)}
        </text>
        <text x={CENTER} y={CENTER + 22} textAnchor="middle" fontSize="9" fill="#64748b">
          / 100 TRUST
        </text>
      </svg>

      {/* Band legend */}
      <ul className="mt-1 flex w-full max-w-[280px] justify-between text-[11px]">
        {SCORE_BANDS.map((b) => (
          <li key={b.label} className="flex items-center gap-1.5 text-text-secondary">
            <span
              className="h-2 w-2 rounded-sm"
              style={{ backgroundColor: b.color }}
              aria-hidden="true"
            />
            <span>
              {b.label}
              <span className="ml-1 text-text-tertiary">
                {b.from}
                {b.to === 100 ? "+" : `–${b.to}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
