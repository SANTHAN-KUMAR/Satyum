import { Tag } from "@/components/primitives/Tag";

/**
 * Renders a signal's real `measurements` payload so the underwriter sees WHY, not just a score
 * (CLAUDE.md §9: "the arithmetic breakdown showing exactly which invariant broke"). Every value comes
 * straight from the backend LayerSignal.measurements — nothing is computed or invented here.
 *
 * The arithmetic engine's `violations[]` get a first-class, human-readable treatment; everything else
 * renders as a faithful key→value table, with narrative footnotes (honest bounds / calibration notes)
 * set apart so they read as caveats, not data.
 */

interface ArithmeticViolation {
  kind: string;
  index: number | null;
  expected: string;
  printed: string;
  delta: string;
}

function isViolation(v: unknown): v is ArithmeticViolation {
  return (
    typeof v === "object" &&
    v !== null &&
    "kind" in v &&
    "expected" in v &&
    "printed" in v &&
    "delta" in v
  );
}

function isNarrativeKey(k: string): boolean {
  return k.endsWith("_note") || k.endsWith("_bound");
}

/** Pixel-coordinate keys are for the document overlay, not the underwriter's reading — hide them. */
function isCoordinateKey(k: string): boolean {
  return /bbox/i.test(k) || k === "evidence_regions";
}

function humanKey(k: string): string {
  return k.replace(/_/g, " ");
}

/** Format an arithmetic figure as Indian-format rupees (₹48,250.00) when it parses as a number. */
function formatMoney(raw: string): string {
  const n = Number(String(raw).replace(/,/g, "").trim());
  if (!Number.isFinite(n)) return raw;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
  }).format(n);
}

function formatScalar(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(3)));
  }
  if (Array.isArray(v)) return v.length ? v.map((x) => formatScalar(x)).join(", ") : "none";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Keys handled by a dedicated renderer or shown elsewhere (cross-doc graph), so skip in the table. */
const HANDLED_KEYS = new Set(["violations", "comparisons"]);

export function MeasurementBreakdown({
  measurements,
}: {
  measurements: Record<string, unknown>;
}) {
  const entries = Object.entries(measurements);
  const violations = Array.isArray(measurements.violations)
    ? (measurements.violations.filter(isViolation) as ArithmeticViolation[])
    : [];

  const scalarEntries = entries.filter(
    ([k, val]) =>
      !HANDLED_KEYS.has(k) && !isNarrativeKey(k) && !isCoordinateKey(k) && typeof val !== "object",
  );
  // Arrays/objects that aren't specially handled — render compactly so nothing is silently dropped.
  const complexEntries = entries.filter(
    ([k, val]) =>
      !HANDLED_KEYS.has(k) &&
      !isNarrativeKey(k) &&
      !isCoordinateKey(k) &&
      typeof val === "object" &&
      val !== null,
  );
  const notes = entries.filter(([k]) => isNarrativeKey(k));

  if (entries.length === 0) {
    return <p className="text-xs text-slate-500">No measurements reported for this signal.</p>;
  }

  return (
    <div className="space-y-3">
      {violations.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-verdict-rejected">
            Arithmetic invariants broken
          </p>
          <ul className="space-y-1.5">
            {violations.map((v, i) => (
              <li
                key={`${v.kind}-${v.index ?? "x"}-${i}`}
                className="rounded-md border border-verdict-rejected/30 bg-verdict-rejected-soft px-2.5 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Tag tone="warn">{humanKey(v.kind)}</Tag>
                  {v.index !== null && <span className="text-slate-400">row {v.index}</span>}
                </div>
                <div className="tnum mt-1.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                  <span className="text-slate-400">expected</span>
                  <span className="font-semibold text-slate-100">{formatMoney(v.expected)}</span>
                  <span className="text-slate-500">but printed</span>
                  <span className="font-semibold text-verdict-rejected">{formatMoney(v.printed)}</span>
                  <span className="text-slate-500">(Δ {formatMoney(v.delta)})</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(scalarEntries.length > 0 || complexEntries.length > 0) && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {scalarEntries.map(([k, val]) => (
            <div key={k} className="flex items-baseline justify-between gap-2 text-xs">
              <dt className="truncate text-slate-500" title={humanKey(k)}>
                {humanKey(k)}
              </dt>
              <dd className="shrink-0 font-mono text-slate-300">{formatScalar(val)}</dd>
            </div>
          ))}
          {complexEntries.map(([k, val]) => (
            <div key={k} className="col-span-full flex items-baseline justify-between gap-2 text-xs">
              <dt className="shrink-0 text-slate-500">{humanKey(k)}</dt>
              <dd className="truncate text-right font-mono text-slate-300" title={formatScalar(val)}>
                {formatScalar(val)}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {notes.map(([k, val]) => (
        <p key={k} className="border-l-2 border-hairline pl-2 text-[11px] italic text-slate-500">
          {formatScalar(val)}
        </p>
      ))}
    </div>
  );
}
