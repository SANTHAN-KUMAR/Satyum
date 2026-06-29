import { AlertTriangle, CheckCircle2, Network, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CrossDocumentMeasurements, CrossFieldStatus, LayerSignal } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

/**
 * The cross-document consistency graph (ADR-003 #3) — the bundle differentiator. A forger can fake
 * one document's pixels, but keeping the SAME identity coherent across a statement + ID + deed is far
 * harder. We extract identity fields (PAN, Aadhaar, IFSC, account, name, DOB) per document and show,
 * field by field, whether the bundle AGREES, is a possible OCR NEAR-match (→ review), or DISAGREES
 * (→ a hard identity mismatch). Every value is read from the cross_document signal's measurements —
 * nothing invented (CLAUDE.md §9).
 */

interface CrossDocumentGraphProps {
  cross: LayerSignal;
  /** All document labels in the bundle (the graph "nodes"), even those with no comparable field. */
  documentLabels: string[];
}

const FIELD_LABEL: Record<string, string> = {
  pan: "PAN",
  aadhaar: "Aadhaar",
  ifsc: "IFSC",
  account_number: "Account no.",
  name: "Name",
  dob: "Date of birth",
};

const STATUS_STYLE: Record<CrossFieldStatus, { label: string; chip: string; Icon: LucideIcon }> = {
  agree: {
    label: "Agree",
    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    Icon: CheckCircle2,
  },
  near: {
    label: "Possible OCR slip",
    chip: "border-verdict-review/40 bg-verdict-review-soft text-verdict-review",
    Icon: AlertTriangle,
  },
  disagree: {
    label: "Mismatch",
    chip: "border-verdict-rejected/40 bg-verdict-rejected-soft text-verdict-rejected",
    Icon: XCircle,
  },
};

function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? field.replace(/_/g, " ");
}

/** Short, human node label from "doc1:bank_statement.png" → "bank_statement.png". */
function nodeLabel(label: string): string {
  const idx = label.indexOf(":");
  return idx >= 0 ? label.slice(idx + 1) : label;
}

export function CrossDocumentGraph({ cross, documentLabels }: CrossDocumentGraphProps) {
  const m = cross.measurements as CrossDocumentMeasurements;
  const comparisons = m.comparisons ?? [];
  const notEvaluated = cross.status === "NOT_EVALUATED";
  const hardMismatch = (m.hard_mismatch_fields ?? []).length > 0;
  const anyDisagree = (m.disagreeing_fields ?? []).length > 0;

  return (
    <Panel
      title="Cross-document identity graph"
      icon={Network}
      aside={
        notEvaluated
          ? "not evaluated"
          : `${comparisons.length} field${comparisons.length === 1 ? "" : "s"} compared`
      }
    >
      {/* Document nodes. */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {documentLabels.map((label) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-2 px-2.5 py-1 text-xs text-slate-200"
            title={label}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
            {nodeLabel(label)}
          </span>
        ))}
      </div>

      {/* Headline status. */}
      <p
        className={cn(
          "mb-3 rounded-lg border px-3 py-2 text-sm",
          notEvaluated
            ? "border-verdict-pending/30 bg-verdict-pending-soft text-verdict-pending"
            : hardMismatch
              ? "border-verdict-rejected/40 bg-verdict-rejected-soft text-verdict-rejected"
              : anyDisagree
                ? "border-verdict-review/40 bg-verdict-review-soft text-verdict-review"
                : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
        )}
      >
        {cross.reason}
      </p>

      {/* Per-field comparison rows. */}
      {notEvaluated || comparisons.length === 0 ? (
        <p className="text-sm text-slate-400">
          No identity field is shared by two or more documents, so there is nothing to cross-check.
          The bundle is not corroborated — but it is not penalised for it (fail-open, never a fake pass).
        </p>
      ) : (
        <ul className="space-y-2">
          {comparisons.map((c) => {
            const style = STATUS_STYLE[c.status];
            const docs = Object.entries(c.values);
            return (
              <li key={c.field} className="rounded-lg border border-hairline bg-canvas/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{fieldLabel(c.field)}</span>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
                      style.chip,
                    )}
                  >
                    <style.Icon size={13} aria-hidden="true" />
                    {style.label}
                  </span>
                </div>
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {docs.map(([doc, value]) => (
                    <div
                      key={doc}
                      className="flex items-baseline justify-between gap-2 rounded-md bg-surface-2/60 px-2 py-1"
                    >
                      <span className="truncate text-[11px] text-slate-500" title={doc}>
                        {nodeLabel(doc)}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 font-mono text-xs",
                          c.status === "agree" ? "text-slate-300" : "text-slate-100",
                        )}
                      >
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
