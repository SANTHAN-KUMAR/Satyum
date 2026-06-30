import { GitBranch, CheckCircle2, XCircle, Clock } from "lucide-react";
import type { Claim } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

/**
 * Layer-2+3 Claim Graph view (ADR-004 §3, §5 VLM trust boundary).
 *
 * Every claim shows:
 *   – the predicate and the value the VLM extracted (box-grounded)
 *   – the value type
 *   – VLM extraction confidence
 *   – what deterministic OCR independently re-read (the cross-read consensus)
 *   – whether VLM and OCR agree (VERIFIED) or disagree (DISAGREED → NOT_EVALUATED)
 *
 * "The VLM reads; deterministic rules decide." A model extraction that disagrees with
 * OCR is surfaced as NOT_EVALUATED — never a silent pick (CLAUDE.md §3.1, ADR-004 §5).
 */

function crossReadIcon(agree: boolean | null) {
  if (agree === true) return { Icon: CheckCircle2, cls: "text-verdict-approved" };
  if (agree === false) return { Icon: XCircle, cls: "text-verdict-rejected" };
  return { Icon: Clock, cls: "text-slate-500" };
}

const STATUS_CHIP_CLS: Record<Claim["status"], string> = {
  VERIFIED:
    "border-verdict-approved/40 bg-verdict-approved-soft text-verdict-approved",
  NOT_EVALUATED:
    "border-verdict-pending/30 bg-verdict-pending-soft text-verdict-pending",
  DISAGREED:
    "border-verdict-rejected/40 bg-verdict-rejected-soft text-verdict-rejected",
};

const STATUS_LABEL: Record<Claim["status"], string> = {
  VERIFIED: "Verified",
  NOT_EVALUATED: "Pending",
  DISAGREED: "Disagreed",
};

function formatBBox(bbox: [number, number, number, number] | null): string {
  if (!bbox) return "no bbox";
  const [x, y, w, h] = bbox;
  return `page bbox (${x},${y}) ${w}×${h}px`;
}

interface ClaimGraphViewProps {
  claims: Claim[];
}

export function ClaimGraphView({ claims }: ClaimGraphViewProps) {
  const disagreed = claims.filter((c) => c.status === "DISAGREED");

  return (
    <Panel
      title="Claim graph"
      icon={GitBranch}
      aside={
        <span className="flex items-center gap-2">
          <span className="text-xs text-slate-400">
            {claims.length} claim{claims.length !== 1 ? "s" : ""}
          </span>
          {disagreed.length > 0 && (
            <span className="rounded-full border border-verdict-rejected/30 bg-verdict-rejected-soft px-2 py-0.5 text-[10px] font-semibold text-verdict-rejected">
              {disagreed.length} VLM↔OCR mismatch
            </span>
          )}
        </span>
      }
      ariaLabel="Extracted claim graph with VLM extraction provenance"
    >
      {claims.length === 0 ? (
        <p className="text-sm text-slate-400">No claims extracted for this document.</p>
      ) : (
        <>
          {/* VLM trust boundary reminder */}
          <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
            VLM reads document → canonical claims · every numeric value independently
            re-read by deterministic OCR · disagreement → Pending, never a silent pick
            (ADR-004 §5).
          </p>

          <div className="overflow-x-auto">
            <table
              className="w-full text-xs"
              aria-label="Canonical claim graph with cross-read status"
            >
              <thead>
                <tr className="border-b border-hairline/60">
                  {["Predicate", "Value", "Type", "Conf.", "OCR re-read", "Status"].map(
                    (col) => (
                      <th
                        key={col}
                        className="pb-2 pr-4 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 last:pr-0"
                        scope="col"
                      >
                        {col}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline/25">
                {claims.map((claim, i) => {
                  const agr = crossReadIcon(claim.provenance.cross_read_agree);
                  const rowCls =
                    claim.status === "DISAGREED"
                      ? "bg-verdict-rejected-soft/20"
                      : "hover:bg-surface-2/30";
                  return (
                    <tr
                      key={`${claim.predicate}-${i}`}
                      className={cn("transition-colors", rowCls)}
                    >
                      <td
                        className="py-2 pr-4 font-mono text-[11px] text-slate-300"
                        title={claim.predicate}
                      >
                        <span className="block max-w-[18ch] truncate">{claim.predicate}</span>
                      </td>
                      <td className="tnum py-2 pr-4 font-semibold text-slate-100">
                        {claim.value}
                      </td>
                      <td className="py-2 pr-4 text-slate-500">{claim.value_type}</td>
                      <td className="tnum py-2 pr-4 text-slate-400">
                        {Math.round(claim.provenance.confidence * 100)}%
                      </td>
                      <td className="py-2 pr-4">
                        <span className="flex items-center gap-1">
                          <agr.Icon size={12} className={agr.cls} aria-hidden="true" />
                          <span
                            className="tnum max-w-[12ch] truncate text-slate-300"
                            title={
                              claim.provenance.corroborating_read ??
                              `page ${claim.provenance.page} · ${formatBBox(claim.provenance.bbox)}`
                            }
                          >
                            {claim.provenance.corroborating_read ?? "—"}
                          </span>
                        </span>
                      </td>
                      <td className="py-2">
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap",
                            STATUS_CHIP_CLS[claim.status],
                          )}
                        >
                          {STATUS_LABEL[claim.status]}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  );
}
