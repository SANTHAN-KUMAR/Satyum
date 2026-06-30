import { useState } from "react";
import { ApiError, verifyDocument } from "@/api/client";
import { approveRule, listRules, mineRules, rejectRule, type LabeledCaseIn, type RuleDto } from "@/api/federation";

/**
 * The Master Model — HOW you test the federated pattern engine (PROPOSAL-001 §6.3.1). It pools
 * labelled outcomes across banks (without sharing raw data) and mines candidate fraud rules; a human
 * approves them into deterministic, auditable rules. This page lets you run a mining round, approve
 * rules into the deployed model, and TEST the deployed model against a case end-to-end.
 *
 * Honest scope: the miner is a real, single-round PoC on the pooled features shown (measured metrics,
 * never invented). The cross-bank training transport is the architectural part.
 */

// The pooled, labelled scenario (88 cases, 12 fraud) — fraud is a conjunction with confounders.
const SCENARIO: LabeledCaseIn[] = [
  ...rep(12, { employer_age_months: 3, loan_amount: 2_500_000, submit_hour: 2 }, true),
  ...rep(40, { employer_age_months: 60, loan_amount: 500_000, submit_hour: 11 }, false),
  ...rep(22, { employer_age_months: 3, loan_amount: 300_000, submit_hour: 2 }, false),
  ...rep(14, { employer_age_months: 70, loan_amount: 2_600_000, submit_hour: 14 }, false),
];
function rep(n: number, features: Record<string, number>, is_fraud: boolean): LabeledCaseIn[] {
  return Array.from({ length: n }, () => ({ features, is_fraud }));
}
const TOTAL = SCENARIO.length;
const FRAUD = SCENARIO.filter((c) => c.is_fraud).length;

const TINY_PDF = new File([new Blob(["%PDF-1.4 test"], { type: "application/pdf" })], "case.pdf", {
  type: "application/pdf",
});

export function IntelligencePage() {
  const [candidates, setCandidates] = useState<RuleDto[] | null>(null);
  const [deployed, setDeployed] = useState<RuleDto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // test-the-model state
  const [loan, setLoan] = useState(2_500_000);
  const [hour, setHour] = useState(2);
  const [empAge, setEmpAge] = useState(3);
  const [testResult, setTestResult] = useState<{ fired: boolean; reason: string } | null>(null);

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

  const mine = () =>
    guard(async () => {
      const res = await mineRules(SCENARIO, "salary_slip_ring");
      setCandidates(res.candidates);
    });

  const decide = (rule: RuleDto, kind: "approve" | "reject") =>
    guard(async () => {
      if (kind === "approve") await approveRule(rule.rule_id, "A. Rao");
      else await rejectRule(rule.rule_id, "A. Rao");
      const all = (await listRules()).rules;
      setCandidates((prev) => prev?.map((r) => all.find((x) => x.rule_id === r.rule_id) ?? r) ?? null);
      setDeployed(all.filter((r) => r.status === "APPROVED"));
    });

  const testModel = () =>
    guard(async () => {
      const res = await verifyDocument(TINY_PDF, {
        docType: "financial_statement",
        features: { loan_amount: loan, submit_hour: hour, employer_age_months: empAge },
      });
      const pr = res.signals.find((s) => s.name === "promoted_rules");
      if (pr && pr.status === "VALID" && (pr.suspicion ?? 0) > 0) {
        setTestResult({ fired: true, reason: pr.reason });
      } else {
        setTestResult({ fired: false, reason: deployed.length ? "No deployed rule matched this case." : "No rule deployed yet — approve one first." });
      }
    });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Master model · federated rule discovery</h1>
        <p className="text-sm text-slate-500">
          The network pools labelled outcomes across banks and mines fraud rules — a human approves them
          into deterministic, auditable rules. Run a round, approve, then test the deployed model.
        </p>
      </div>

      {/* training data */}
      <section className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-navy">Pooled training data</h2>
            <p className="mt-1 text-sm text-slate-400">
              {TOTAL} labelled cases · <b className="text-verdict-rejected">{FRAUD} confirmed frauds</b> pooled across
              banks (no raw data shared). Rare positives no single bank could learn from alone.
            </p>
          </div>
          <button onClick={mine} disabled={busy} className="btn-primary">
            {busy ? "Mining…" : "Run a federated mining round"}
          </button>
        </div>
      </section>

      {/* candidates */}
      {candidates && (
        <section className="panel p-5">
          <h2 className="text-base font-semibold text-navy">Candidate rules ({candidates.length})</h2>
          <p className="mt-1 text-sm text-slate-400">Measured on the pooled data — approve to deploy into the model.</p>
          <ul className="mt-4 space-y-3">
            {candidates.map((c) => (
              <li key={c.rule_id} className="rounded-xl border border-hairline bg-surface-2/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-sm font-semibold text-navy">{c.rule_id}</p>
                    <p className="mt-0.5 break-words text-sm text-slate-300">{c.predicates}</p>
                    <p className="mt-1 text-xs text-slate-500 tnum">
                      confidence {c.confidence} · support {c.support} · lift {c.lift}
                    </p>
                  </div>
                  {c.status === "APPROVED" ? (
                    <span className="rounded-full bg-verdict-approved-soft px-3 py-1 text-xs font-semibold text-verdict-approved">
                      ✓ Deployed
                    </span>
                  ) : c.status === "REJECTED" ? (
                    <span className="rounded-full bg-surface-2 px-3 py-1 text-xs text-slate-500">Rejected</span>
                  ) : (
                    <div className="flex gap-2">
                      <button onClick={() => decide(c, "approve")} disabled={busy} className="btn-primary !py-1.5 !text-xs">
                        Approve
                      </button>
                      <button onClick={() => decide(c, "reject")} disabled={busy} className="btn-ghost !py-1.5 !text-xs">
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* test the model */}
      <section className="panel p-5">
        <h2 className="text-base font-semibold text-navy">Test the deployed model against a case</h2>
        <p className="mt-1 text-sm text-slate-400">
          Enter an application’s features and run it through the real verification pipeline — the
          deployed deterministic rules fire with an explanation (never a black-box score).
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Num label="Loan amount (₹)" value={loan} onChange={setLoan} step={100000} />
          <Num label="Submit hour (0–23)" value={hour} onChange={setHour} step={1} />
          <Num label="Employer age (months)" value={empAge} onChange={setEmpAge} step={1} />
        </div>
        <button onClick={testModel} disabled={busy} className="btn-primary mt-4">
          Run against the model
        </button>
        {testResult && (
          <div
            className={
              "mt-4 rounded-xl border p-4 text-sm " +
              (testResult.fired ? "border-verdict-review/30 bg-verdict-review-soft text-slate-300" : "border-hairline bg-surface-2/50 text-slate-400")
            }
          >
            {testResult.fired ? <b className="text-verdict-review">⚠ Rule fired. </b> : <b>No rule fired. </b>}
            {testResult.reason}
          </div>
        )}
      </section>

      {error && <p className="text-sm text-verdict-rejected">⚠ {error}</p>}
    </div>
  );
}

function Num({ label, value, onChange, step }: { label: string; value: number; onChange: (n: number) => void; step: number }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full rounded-xl border border-hairline bg-surface px-3 py-2 text-slate-100 outline-none focus:border-navy tnum"
      />
    </label>
  );
}
