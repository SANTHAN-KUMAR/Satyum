import { useState } from "react";
import { ApiError, verifyDocument } from "@/api/client";
import { createCase, getCase, type CaseView } from "@/api/cases";
import { useCopilotContext } from "@/lib/CopilotContext";
import { CaseIdentityMatrix } from "@/components/evidence/CaseIdentityMatrix";

/**
 * The application-case file. An underwriter opens a case for an applicant, then adds their documents
 * one at a time (PAN, bank statement, Form-16, Aadhaar). Each document is verified and its extracted
 * identity claims accrue into the case, so the cross-document corroboration graph strengthens as more
 * documents arrive — two documents that agree corroborate one identity, a third strengthens it, and one
 * that disagrees on a hard identifier (PAN / Aadhaar / account) flags identity fraud. Only the extracted
 * claims and verdicts are stored, never the document bytes or imagery.
 */
export function CasePage() {
  const [current, setCurrent] = useState<CaseView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setCopilotContext } = useCopilotContext();

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setCurrent(await createCase());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not open a case.");
    } finally {
      setBusy(false);
    }
  };

  const addDocument = async (file: File | null) => {
    if (!file || !current) return;
    setBusy(true);
    setError(null);
    try {
      // verifyDocument returns this document's own full TrustScore/evidence pack even inside a case —
      // that's real data, so it becomes the global Copilot's active context immediately (not the whole
      // case, which has no evidence-pack-shaped object of its own — see CLAUDE.md §9 on not fabricating).
      const result = await verifyDocument(file, { caseId: current.case_id });
      setCopilotContext(result.evidence_pack, file.name);
      setCurrent(await getCase(current.case_id)); // refresh: the graph has re-run over all documents
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add the document.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-navy">Application case file</h1>
          <p className="mt-1 text-sm text-slate-500">
            Add an applicant’s documents one at a time. The cross-document identity graph gets stronger
            with each one.
          </p>
        </div>
        {current && (
          <button onClick={start} disabled={busy} className="btn-ghost text-sm">
            + New case
          </button>
        )}
      </div>

      {!current ? (
        <div className="mt-10 rounded-3xl border border-hairline bg-surface p-10 text-center">
          <p className="text-sm text-slate-400">
            Open a case for an applicant, then add each document you receive. Corroboration accumulates
            across every document in the case.
          </p>
          <button onClick={start} disabled={busy} className="btn-gradient mt-6">
            {busy ? "Opening…" : "Open a new application case"}
          </button>
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          <CorroborationBanner c={current} />

          {/* The matrix itself — surfaced inline immediately, not behind a tab or another page, so the
              per-field visual proof is right where the corroboration claim is made. */}
          {current.documents.length >= 2 && (
            <CaseIdentityMatrix
              documents={current.documents}
              hardMismatchFields={current.hard_mismatch_fields}
              comparisons={current.comparisons}
            />
          )}

          <div className="rounded-2xl border border-hairline bg-surface p-5">
            <p className="text-sm font-medium text-navy">Add a document to this case</p>
            <p className="mt-1 text-xs text-slate-500">
              PAN, bank statement, Form-16, Aadhaar. Each is verified, and its identity claims accrue.
            </p>
            <label
              htmlFor="case-file"
              className="mt-4 block cursor-pointer rounded-2xl border border-dashed border-hairline bg-surface-2/40 p-6 text-center transition hover:border-ink/40"
            >
              <input
                id="case-file"
                type="file"
                accept="application/pdf,.pdf,image/*"
                className="hidden"
                disabled={busy}
                onChange={(e) => addDocument(e.target.files?.[0] ?? null)}
              />
              <span className="gradient-text text-sm font-semibold">
                {busy ? "Verifying & adding…" : "Add a document"}
              </span>
            </label>
          </div>

          <div className="rounded-2xl border border-hairline bg-surface p-5">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-navy">Documents in this case</p>
              <span className="text-xs text-slate-500">{current.document_count} total</span>
            </div>
            {current.documents.length === 0 ? (
              <p className="mt-3 text-sm text-slate-500">No documents yet. Add the first one above.</p>
            ) : (
              <ul className="mt-3 divide-y divide-hairline">
                {current.documents.map((d) => (
                  <li key={d.doc_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-200">{d.label}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {Object.keys(d.identity).length
                          ? Object.entries(d.identity)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(" · ")
                          : "no comparable identity fields"}
                      </p>
                    </div>
                    <VerdictPill verdict={d.verdict} />
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="text-xs text-slate-500">
            Case {current.case_id} · only extracted claims and verdicts are stored, never document bytes.
          </p>
        </div>
      )}

      {error && <p className="mt-4 text-sm text-verdict-rejected">⚠ {error}</p>}
    </div>
  );
}

function CorroborationBanner({ c }: { c: CaseView }) {
  const pending = c.corroboration_status === "NOT_EVALUATED";
  const mismatch = c.hard_mismatch_fields.length > 0;
  const tone = mismatch
    ? "border-verdict-rejected/40 bg-verdict-rejected-soft"
    : pending
      ? "border-hairline bg-surface-2/40"
      : "glass";
  return (
    <div className={"rounded-3xl border p-6 " + tone}>
      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Cross-document corroboration</p>
      <p
        className={
          "mt-1 text-xl font-semibold " +
          (mismatch ? "text-verdict-rejected" : pending ? "text-slate-300" : "gradient-text")
        }
      >
        {mismatch
          ? `✕ Identity mismatch — ${c.hard_mismatch_fields.join(", ")} differs across documents`
          : pending
            ? "Add a second document to begin corroboration"
            : `✓ Identity corroborated across ${c.document_count} documents`}
      </p>
      {c.corroboration_reason && (
        <p className="mt-2 text-sm text-slate-400">{c.corroboration_reason}</p>
      )}
    </div>
  );
}

const VERDICT_TONE: Record<string, string> = {
  APPROVED: "text-verdict-approved",
  REVIEW: "text-verdict-review",
  REJECTED: "text-verdict-rejected",
};

function VerdictPill({ verdict }: { verdict: string }) {
  return (
    <span
      className={
        "rounded-full border border-hairline px-3 py-1 text-xs font-semibold " +
        (VERDICT_TONE[verdict] ?? "text-slate-400")
      }
    >
      {verdict}
    </span>
  );
}
