import { AlertTriangle, CheckCircle2, Network, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CaseDocumentView } from "@/api/cases";
import type { CrossFieldComparison, CrossFieldStatus } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { cn } from "@/lib/cn";

interface CaseIdentityMatrixProps {
  documents: CaseDocumentView[];
  hardMismatchFields: string[];
  /** Real per-field comparisons from backend/app/routes/cases.py::FieldComparisonView. */
  comparisons: CrossFieldComparison[];
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
  agree: { label: "Agree", chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300", Icon: CheckCircle2 },
  near: { label: "Possible OCR slip", chip: "border-verdict-review/40 bg-verdict-review-soft text-verdict-review", Icon: AlertTriangle },
  disagree: { label: "Mismatch", chip: "border-verdict-rejected/40 bg-verdict-rejected-soft text-verdict-rejected", Icon: XCircle },
};

function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? field.replace(/_/g, " ");
}

/**
 * Fallback for a case snapshot that predates the `comparisons` field (defensive only — every live
 * backend now sends it). Derives a coarser 2-tier view (agree / hard mismatch) purely from identity
 * values already present, since there's no near-match data to fall back on.
 */
function deriveFromIdentity(documents: CaseDocumentView[], hardMismatchFields: string[]): CrossFieldComparison[] {
  const fields = new Set<string>();
  for (const d of documents) for (const f of Object.keys(d.identity)) fields.add(f);

  const rows: CrossFieldComparison[] = [];
  for (const field of fields) {
    const values: Record<string, string> = {};
    for (const d of documents) {
      const v = d.identity[field];
      if (v) values[d.label] = v;
    }
    if (Object.keys(values).length < 2) continue; // nothing to compare — not shown, not penalised

    const distinct = new Set(Object.values(values).map((v) => v.trim().toUpperCase()));
    const status: CrossFieldStatus = hardMismatchFields.includes(field) ? "disagree" : distinct.size === 1 ? "agree" : "disagree";
    rows.push({ field, status, agree: status === "agree", values });
  }
  return rows;
}

/**
 * The case-level identity matrix — the same visual language and, now that
 * backend/app/routes/cases.py forwards the real `comparisons[]`, the same 3-tier granularity
 * (agree / near-OCR-slip / disagree) as the bundle path's CrossDocumentGraph. Rendered inline on
 * CasePage immediately below the corroboration banner — the visual proof sits where the claim is made.
 */
export function CaseIdentityMatrix({ documents, hardMismatchFields, comparisons }: CaseIdentityMatrixProps) {
  const rows = comparisons.length > 0 ? comparisons : deriveFromIdentity(documents, hardMismatchFields);
  const order: Record<CrossFieldStatus, number> = { disagree: 0, near: 1, agree: 2 };
  const sorted = [...rows].sort((a, b) => order[a.status] - order[b.status]);

  return (
    <Panel title="Cross-document identity matrix" icon={Network} aside={`${sorted.length} field${sorted.length === 1 ? "" : "s"} compared`}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {documents.map((d) => (
          <span
            key={d.doc_id}
            className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-muted px-2.5 py-1 text-xs text-text-primary"
            title={d.label}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
            {d.label}
          </span>
        ))}
      </div>

      {sorted.length === 0 ? (
        <p className="text-sm text-text-secondary">
          No identity field is shared by two or more documents yet, so there is nothing to cross-check.
          Add another document to start corroborating identity.
        </p>
      ) : (
        <ul className="space-y-2">
          {sorted.map((r) => {
            const style = STATUS_STYLE[r.status];
            return (
              <li key={r.field} className="rounded-lg border border-hairline bg-canvas/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{fieldLabel(r.field)}</span>
                  <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium", style.chip)}>
                    <style.Icon size={13} aria-hidden="true" />
                    {style.label}
                  </span>
                </div>
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {Object.entries(r.values).map(([doc, value]) => (
                    <div key={doc} className="flex items-baseline justify-between gap-2 rounded-md bg-surface-muted/60 px-2 py-1">
                      <span className="truncate text-[11px] text-text-tertiary" title={doc}>
                        {doc}
                      </span>
                      <span className={cn("shrink-0 font-mono text-xs", r.status === "agree" ? "text-text-secondary" : "text-text-primary")}>
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
