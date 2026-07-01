import type { RingEvidence } from "@/api/federation";

/**
 * A live SVG of a detected ring: member applications on a ring, each linked to the shared-identifier
 * hub at the centre. Monochrome (ink nodes) with the highlight gradient on the links + hub — the
 * tokenised connections that, pooled across banks, reveal the ring (§6.1).
 */
export function RingGraph({ ring }: { ring: RingEvidence }) {
  const size = 360;
  const cx = size / 2;
  const cy = size / 2;
  const r = 128;
  const members = ring.members;
  const n = Math.max(members.length, 1);

  const points = members.map((m, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), label: m };
  });

  return (
    <figure className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-auto w-full max-w-sm" role="img"
        aria-label={`Ring of ${members.length} applications across ${ring.banks.length} banks`}>
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FF9933" />
            <stop offset="52%" stopColor="#000080" />
            <stop offset="100%" stopColor="#138808" />
          </linearGradient>
        </defs>

        {/* links — gradient */}
        {points.map((p, i) => (
          <line key={`l-${i}`} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="url(#ringGrad)" strokeWidth={2} strokeOpacity={0.8} />
        ))}

        {/* centre hub — gradient ring */}
        <circle cx={cx} cy={cy} r={30} fill="#ffffff" stroke="url(#ringGrad)" strokeWidth={2.5} />
        <text x={cx} y={cy - 2} textAnchor="middle" className="fill-slate-100" fontSize="10" fontWeight={700}>shared</text>
        <text x={cx} y={cy + 11} textAnchor="middle" className="fill-slate-400" fontSize="9">
          {Object.keys(ring.shared_identifiers).length} links
        </text>

        {/* member nodes — ink */}
        {points.map((p, i) => {
          const bank = p.label.split(":")[0] ?? p.label;
          return (
            <g key={`n-${i}`}>
              <circle cx={p.x} cy={p.y} r={22} fill="#0A0A0A" />
              <text x={p.x} y={p.y + 3} textAnchor="middle" className="fill-white" fontSize="9" fontWeight={600}>
                {bank.slice(0, 6)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-3 flex flex-wrap justify-center gap-2">
        {Object.entries(ring.shared_identifiers).map(([kind, count]) => (
          <span key={kind} className="glass rounded-full px-2.5 py-1 text-[11px] font-medium text-slate-300">
            {kind.replace(/_/g, " ")} · {count}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/**
 * A muted, non-data illustration of the ring topology (generic 5-node placeholder), shown before any
 * ring has actually been detected. Its only job is discoverability — so the "what does a detected ring
 * look like" graph is visible immediately instead of appearing only after 3+ manual submissions. It
 * renders no real measurements and is clearly labelled illustrative — not a result (CLAUDE.md §9).
 */
export function RingGraphGhost() {
  const size = 360;
  const cx = size / 2;
  const cy = size / 2;
  const r = 128;
  const n = 5;
  const points = Array.from({ length: n }, (_, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });

  return (
    <figure className="flex flex-col items-center opacity-40" aria-hidden="true">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-auto w-full max-w-sm">
        {points.map((p, i) => (
          <line key={`l-${i}`} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#A1A1AA" strokeWidth={2} strokeDasharray="4 4" />
        ))}
        <circle cx={cx} cy={cy} r={30} fill="none" stroke="#A1A1AA" strokeWidth={2} strokeDasharray="4 4" />
        {points.map((p, i) => (
          <circle key={`n-${i}`} cx={p.x} cy={p.y} r={20} fill="#F5F5F6" stroke="#A1A1AA" strokeWidth={1.5} />
        ))}
      </svg>
    </figure>
  );
}
