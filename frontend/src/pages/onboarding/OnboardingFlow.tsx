import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, PasswordRequiredError, verifyDocument } from "@/api/client";
import { pullSource, type SourceResult } from "@/api/federation";
import type { TrustScore } from "@/api/types";
import { validatePanStructure } from "@/lib/pan";
import { setLastCase } from "@/lib/lastResult";
import { Stepper } from "@/components/onboarding/Stepper";
import { BackendStatus } from "@/components/shell/BackendStatus";

const STEPS = [
  { title: "Identity", sub: "Who is applying" },
  { title: "Source check", sub: "Verify the issuer's signature" },
  { title: "Review", sub: "Confirm the details" },
  { title: "Decision", sub: "Submit & verify" },
];

/**
 * The applicant onboarding journey — premium, white-major, with the flag colours appearing ONLY as a
 * gradient highlight and frosted glass on the emphasised pieces (PROPOSAL-001 §4; brand direction:
 * monochrome base, gradient highlights, glassmorphism). Progressive disclosure, instant validation,
 * source-pull-first, and a clean hand-off into the underwriter console.
 */
export function OnboardingFlow() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);

  const [name, setName] = useState("");
  const [pan, setPan] = useState("");
  const [mobile, setMobile] = useState("");
  const [dob, setDob] = useState(""); // DD/MM/YYYY

  // Live PAN verification (real, against the Income-Tax PAN database when the provider is configured).
  const [panResult, setPanResult] = useState<SourceResult | null>(null);
  const [panChecking, setPanChecking] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [pulling, setPulling] = useState(false);
  const [source, setSource] = useState<SourceResult | null>(null);
  const [sourcePassword, setSourcePassword] = useState("");
  const [sourceNeedsPassword, setSourceNeedsPassword] = useState<{ error?: string } | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [trust, setTrust] = useState<TrustScore | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Encrypted-PDF unlock: when the backend asks for a password, we prompt here and resubmit. The
  // password is decrypted in memory server-side, so the original signed bytes are preserved.
  const [pdfPassword, setPdfPassword] = useState("");
  const [passwordNeeded, setPasswordNeeded] = useState<{ error?: string } | null>(null);

  const panCheck = useMemo(() => validatePanStructure(pan), [pan]);
  const dobValid = /^[0-3]?\d\/[0-1]?\d\/\d{4}$/.test(dob);
  const identityValid = name.trim().length > 1 && panCheck.ok && /^[0-9]{10}$/.test(mobile) && dobValid;

  const goNext = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const goBack = () => setStep((s) => Math.max(s - 1, 0));

  // Verify the PAN live; returns the result so the caller can gate on a real mismatch.
  const verifyPan = async (): Promise<SourceResult | null> => {
    setPanChecking(true);
    setError(null);
    try {
      const res = await pullSource("pan", {
        doc_class: "identity",
        consent_id: `c-${crypto.randomUUID().slice(0, 8)}`,
        applicant_ref: pan,
        name,
        dob,
      });
      setPanResult(res.source_result);
      return res.source_result;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the PAN verification service.");
      return null;
    } finally {
      setPanChecking(false);
    }
  };

  // Continue from Identity: run the real PAN check first. We do NOT advance silently —
  //   - backend unreachable    -> blocked (a down backend can't wave a PAN through);
  //   - PAN INVALID / mismatch  -> blocked (the real fraud catch);
  //   - VERIFIED or honest gate -> advance, the banner stating which.
  const continueIdentity = async () => {
    if (!identityValid) return;
    const res = panResult ?? (await verifyPan());
    if (!res) {
      setError("Couldn't reach the backend to verify your PAN. Make sure the backend is running (port 8000) — see the status indicator.");
      return;
    }
    if (res.signature_status === "INVALID") return; // real PAN failure — the banner explains why
    goNext();
  };

  const runPull = async () => {
    if (!file) return;
    setPulling(true);
    setError(null);
    try {
      const res = await pullSource(
        "digilocker",
        {
          doc_class: "financial_statement",
          consent_id: `c-${crypto.randomUUID().slice(0, 8)}`,
          issuer_hint: "sbi",
          applicant_ref: pan,
          pdf_password: sourcePassword || undefined,
        },
        file,
      );
      if (res.needs_password) {
        // Locked govt PDF (e.g. a downloaded Aadhaar). Prompt for the password and decrypt in memory.
        setSourceNeedsPassword({ error: res.password_error ?? undefined });
      } else {
        setSourceNeedsPassword(null);
        setSource(res.source_result);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not verify at source.");
    } finally {
      setPulling(false);
    }
  };

  const submit = async () => {
    if (!file) {
      setError("Please add your statement in the previous step.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // Don't force a document type: let the backend classify the upload (the VLM reads its real type,
      // e.g. BANK_STATEMENT vs PAN_CARD). Forcing "financial_statement" mislabelled non-statements (a
      // PAN showed as a financial statement) and mis-routed their forensics. Classification is honest.
      const result = await verifyDocument(file, {
        claimedPan: pan,
        claimedName: name || undefined,
        password: pdfPassword || undefined,
      });
      setTrust(result);
      setPasswordNeeded(null);
      setStep(3);
    } catch (e) {
      if (e instanceof PasswordRequiredError) {
        // Recoverable: the PDF is locked. Show the password field (and a "wrong password" note if any).
        setPasswordNeeded({ error: e.passwordError });
      } else {
        setError(e instanceof ApiError ? e.message : "Verification failed.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const openConsole = () => {
    if (!trust || !file) return;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    setLastCase({ trust, fileName: file.name, isPdf, previewUrl: isPdf ? null : URL.createObjectURL(file) });
    navigate("/console");
  };

  return (
    <div className="min-h-full lg:grid lg:grid-cols-[440px_1fr]">
      {/* LEFT — aurora + glass brand/stepper (desktop) */}
      <aside className="aurora relative hidden flex-col justify-between p-10 lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <span className="gradient-accent flex h-11 w-11 items-center justify-center rounded-2xl text-lg text-white shadow-card">
              सत्
            </span>
            <div>
              <p className="text-lg font-semibold text-slate-100">Satyum</p>
              <p className="text-xs text-slate-500">Home loan · document verification</p>
            </div>
          </div>
          <h1 className="mt-10 text-3xl font-semibold leading-tight text-slate-100">
            Verified at the <span className="gradient-text">source</span>.<br />
            Nothing left to forge.
          </h1>
          <p className="mt-3 max-w-xs text-sm text-slate-500">
            A few quick steps. We verify your documents cryptographically — you never hand over anything
            forgeable.
          </p>
        </div>

        <div className="glass rounded-3xl p-6">
          <Stepper steps={STEPS} current={step} />
        </div>

        <div className="space-y-3">
          <BackendStatus />
          <p className="text-xs text-slate-500">🔒 Source-verified · tokenised · never stored.</p>
        </div>
      </aside>

      {/* RIGHT — content */}
      <main className="flex min-h-full items-center justify-center bg-surface px-5 py-10 sm:px-8">
        <div className="w-full max-w-md">
          {/* mobile brand + progress */}
          <div className="mb-8 lg:hidden">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="gradient-accent flex h-9 w-9 items-center justify-center rounded-xl text-white">सत्</span>
                <span className="font-semibold text-slate-100">Satyum</span>
              </div>
              <button onClick={() => navigate("/console")} className="text-sm text-slate-400">
                Bank staff →
              </button>
            </div>
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div className="gradient-accent h-full rounded-full transition-all" style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
            </div>
            <div className="mt-2 flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Step {step + 1} of {STEPS.length} · {STEPS[step]!.title}
              </p>
              <BackendStatus compact />
            </div>
          </div>

          <div className="animate-fade-in">
            {step === 0 && (
              <Identity
                name={name} pan={pan} mobile={mobile} dob={dob} panCheck={panCheck} panResult={panResult}
                onName={(v) => { setName(v); setPanResult(null); }}
                onPan={(v) => { setPan(v.toUpperCase()); setPanResult(null); }}
                onMobile={(v) => setMobile(v.replace(/[^0-9]/g, "").slice(0, 10))}
                onDob={(v) => { setDob(v); setPanResult(null); }}
              />
            )}
            {step === 1 && (
              <SourceStep file={file} pulling={pulling} source={source}
                onFile={(f) => { setFile(f); setSource(null); setSourceNeedsPassword(null); setSourcePassword(""); }}
                onPull={runPull}
                needsPassword={sourceNeedsPassword}
                password={sourcePassword} onPassword={setSourcePassword} />
            )}
            {step === 2 && <Review name={name} pan={pan} entityType={panCheck.entityType} source={source} fileName={file?.name ?? null} />}
            {step === 3 && trust && <Decision trust={trust} onOpenConsole={openConsole} />}

            {passwordNeeded && (
              <PasswordPrompt
                value={pdfPassword}
                onChange={setPdfPassword}
                error={passwordNeeded.error}
                onSubmit={submit}
                submitting={submitting}
              />
            )}

            {error && <p className="mt-4 text-sm text-verdict-rejected">⚠ {error}</p>}

            {step < 3 && (
              <div className="mt-8 flex items-center justify-between">
                <button onClick={goBack} disabled={step === 0} className="btn-ghost disabled:opacity-30">
                  Back
                </button>
                {step === 0 && (
                  <button onClick={continueIdentity} disabled={!identityValid || panChecking} className="btn-gradient">
                    {panChecking ? "Verifying PAN…" : "Continue →"}
                  </button>
                )}
                {step === 1 && (
                  <button onClick={goNext} disabled={!file} className="btn-gradient">
                    Continue →
                  </button>
                )}
                {step === 2 && (
                  <button onClick={submit} disabled={submitting || !file} className="btn-gradient">
                    {submitting ? "Verifying…" : "Submit application"}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// --- step 0: identity ----------------------------------------------------------------------------

const INPUT =
  "mt-1.5 w-full rounded-xl border border-hairline bg-surface px-3.5 py-3 text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-ink";

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-300">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs">{hint}</span>}
    </label>
  );
}

/**
 * Inline unlock for a password-protected PDF (DigiLocker / Aadhaar / CAMS / bank e-statements). The
 * password is decrypted in memory on the server, so the document's original signed bytes are never
 * re-saved and its digital signature is preserved.
 */
function PasswordPrompt({
  value, onChange, error, onSubmit, submitting,
}: {
  value: string; onChange: (v: string) => void; error?: string;
  onSubmit: () => void; submitting: boolean;
}) {
  return (
    <div className="mt-5 rounded-2xl border border-hairline bg-surface-2/40 p-4">
      <p className="text-sm font-medium text-slate-200">This document is password-protected</p>
      <p className="mt-1 text-xs text-slate-500">
        Enter the document password. We unlock it in memory to read and verify it; the file and its
        digital signature are never altered.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="password"
          className={INPUT + " max-w-[220px] flex-1"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && value && !submitting) onSubmit(); }}
          placeholder="Document password"
          aria-label="Document password"
          autoFocus
        />
        <button onClick={onSubmit} disabled={!value || submitting} className="btn-primary">
          {submitting ? "Unlocking…" : "Unlock & verify"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-verdict-rejected">⚠ {error}</p>}
    </div>
  );
}

function Identity({
  name, pan, mobile, dob, panCheck, panResult, onName, onPan, onMobile, onDob,
}: {
  name: string; pan: string; mobile: string; dob: string;
  panCheck: ReturnType<typeof validatePanStructure>;
  panResult: SourceResult | null;
  onName: (v: string) => void; onPan: (v: string) => void; onMobile: (v: string) => void; onDob: (v: string) => void;
}) {
  return (
    <div>
      <h2 className="text-2xl font-semibold text-slate-100">
        Let’s start with who’s <span className="gradient-text">applying</span>
      </h2>
      <p className="mt-1.5 text-sm text-slate-400">
        We validate the <span className="gradient-text font-medium">PAN format</span> instantly. A live
        Income-Tax existence check is a labelled production gate (it needs a regulator credential) — so
        here we cross-check this PAN against the <span className="gradient-text font-medium">documents you
          submit</span>, the way an underwriter would.
      </p>
      <div className="mt-7 grid gap-5">
        <Field label="Full name (as on PAN)">
          <input className={INPUT} value={name} onChange={(e) => onName(e.target.value)} placeholder="e.g. Asha Kumar" />
        </Field>
        <Field
          label="PAN"
          hint={pan && (
            <span className={panCheck.ok ? "gradient-text font-semibold" : "text-verdict-review"}>
              {panCheck.ok ? "✓ " : "• "}{panCheck.message}
            </span>
          )}
        >
          <input className={INPUT + " font-mono tracking-wide"} value={pan} onChange={(e) => onPan(e.target.value)}
            placeholder="AAAAA9999A" maxLength={10} aria-invalid={pan.length > 0 && !panCheck.ok} />
        </Field>
        <Field label="Date of birth" hint={<span className="text-slate-500">DD/MM/YYYY — used for the PAN check.</span>}>
          <input className={INPUT} value={dob} onChange={(e) => onDob(e.target.value)} placeholder="01/01/1990" inputMode="numeric" />
        </Field>
        <Field label="Mobile number" hint={<span className="text-slate-500">For your application record &amp; contact — not a verification signal.</span>}>
          <div className="mt-1.5 flex items-center rounded-xl border border-hairline bg-surface focus-within:border-ink">
            <span className="px-3.5 text-sm text-slate-500">+91</span>
            <input className="w-full bg-transparent py-3 pr-3 text-slate-100 outline-none" value={mobile}
              onChange={(e) => onMobile(e.target.value)} placeholder="98765 43210" inputMode="numeric" />
          </div>
        </Field>
      </div>

      {/* live PAN verification result */}
      {panResult && <PanResultBanner result={panResult} />}

      {/* optional Aadhaar offline e-KYC verification */}
      <AadhaarVerify />
    </div>
  );
}

function AadhaarVerify() {
  const [file, setFile] = useState<File | null>(null);
  const [shareCode, setShareCode] = useState("");
  const [result, setResult] = useState<SourceResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const verify = async () => {
    if (!file) return;
    setChecking(true);
    setErr(null);
    try {
      const res = await pullSource(
        "aadhaar_offline",
        { doc_class: "identity", consent_id: `c-${crypto.randomUUID().slice(0, 8)}`, share_code: shareCode || undefined },
        file,
      );
      setResult(res.source_result);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not verify Aadhaar.");
    } finally {
      setChecking(false);
    }
  };

  const verified = result?.signature_status === "VERIFIED";

  // A photo/scan of the physical card has no digital signature to verify (it isn't the offline e-KYC
  // package UIDAI issues), so we catch that client-side and explain instead of sending it to the backend
  // to fail as "malformed XML" — an honest, actionable message beats a raw provider rejection.
  const looksLikeImage = file != null && file.type.startsWith("image/");
  // A signed e-Aadhaar PDF (e.g. pulled from DigiLocker) is a real, verifiable document — but this
  // provider only parses the offline e-KYC ZIP/XML package, not a PDF. Route the user to the step that
  // actually handles signed PDFs instead of letting the upload dead-end here.
  const looksLikePdf = file != null && (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
  const blocked = looksLikeImage || looksLikePdf;

  return (
    <div className="mt-6 rounded-2xl border border-hairline p-4">
      <p className="text-sm font-semibold text-slate-300">
        Aadhaar — offline e-KYC <span className="font-normal text-slate-500">(optional · strengthens corroboration)</span>
      </p>
      <p className="mt-2 text-xs text-slate-500">
        Generate an Aadhaar Paperless Offline e-KYC at myaadhaar.uidai.gov.in, then upload the ZIP and
        enter its share code. We verify UIDAI’s digital signature on that package (only a masked
        reference is used) — <span className="font-medium text-slate-400">a photo of the physical card
        can’t be cryptographically verified and won’t be accepted here. Have a signed e-Aadhaar
        PDF instead (e.g. from DigiLocker)? Use “Verify your statement at the source” in the next
        step — that's the slot that verifies a signed PDF.</span>
      </p>
      <div className="mt-3 grid gap-3">
        <input
          type="file"
          accept=".zip,.xml,.pdf,application/zip,text/xml,application/pdf,image/*"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
          className="block w-full text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-ink file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
        />
        <input
          className={INPUT + " max-w-[180px]"}
          value={shareCode}
          onChange={(e) => { setShareCode(e.target.value); setResult(null); }}
          placeholder="Share code (e.g. ABCD)"
          maxLength={12}
        />
        <button onClick={verify} disabled={!file || checking || blocked} className="btn-ghost w-fit">
          {checking ? "Verifying…" : "Verify Aadhaar"}
        </button>
      </div>
      {looksLikeImage && (
        <p className="mt-2 text-xs text-verdict-review">
          ⚠ This looks like a photo, not an offline e-KYC package — see the instructions above. Get the
          ZIP from myaadhaar.uidai.gov.in instead.
        </p>
      )}
      {looksLikePdf && (
        <p className="mt-2 text-xs text-verdict-review">
          ⚠ This looks like a signed PDF, not an offline e-KYC ZIP/XML package — this section can't verify
          it. Use “Verify your statement at the source” in the next step instead.
        </p>
      )}
      {result && (
        <div
          className={
            "mt-3 rounded-xl p-3 text-sm " +
            (verified
              ? "glass"
              : result.signature_status === "INVALID"
                ? "border border-verdict-rejected/30 bg-verdict-rejected-soft text-verdict-rejected"
                : "border border-verdict-review/30 bg-verdict-review-soft text-slate-400")
          }
        >
          {verified ? (
            <>
              <span className="gradient-text font-semibold">✓ Aadhaar verified</span>{" "}
              <span className="text-slate-400">
                — UIDAI-signed, reference {String((result.measurements?.reference_id as string) ?? "—")}.
              </span>
            </>
          ) : (
            <>{result.detail}</>
          )}
        </div>
      )}
      {err && <p className="mt-2 text-xs text-verdict-rejected">⚠ {err}</p>}
    </div>
  );
}

function PanResultBanner({ result }: { result: SourceResult }) {
  if (result.signature_status === "VERIFIED") {
    return (
      <div className="glass mt-5 rounded-xl p-3 text-sm">
        <span className="gradient-text font-semibold">✓ PAN verified</span>{" "}
        <span className="text-slate-400">against the Income-Tax database{result.measurements?.name_as_per_pan_match ? " · name matches" : ""}.</span>
      </div>
    );
  }
  if (result.signature_status === "INVALID") {
    return (
      <div className="mt-5 rounded-xl border border-verdict-rejected/30 bg-verdict-rejected-soft p-3 text-sm text-verdict-rejected">
        ✕ {result.detail}
      </div>
    );
  }
  // NOT_VERIFIED — honest gate (provider not configured): format ok, existence not checked.
  return (
    <div className="mt-5 rounded-xl border border-verdict-review/30 bg-verdict-review-soft p-3 text-sm text-slate-400">
      ⓘ Format valid. Live PAN verification isn’t configured on this server — {result.gate ? "set a provider key to enable it." : "continuing on structure only."}
    </div>
  );
}

// --- step 1: source-pull -------------------------------------------------------------------------

function SourceStep({
  file, pulling, source, onFile, onPull, needsPassword, password, onPassword,
}: {
  file: File | null; pulling: boolean; source: SourceResult | null;
  onFile: (f: File | null) => void; onPull: () => void;
  needsPassword: { error?: string } | null;
  password: string; onPassword: (v: string) => void;
}) {
  const status = source?.signature_status;
  const verified = status === "VERIFIED";
  return (
    <div>
      <h2 className="text-2xl font-semibold text-slate-100">
        Verify your statement at the <span className="gradient-text">source</span>
      </h2>
      <p className="mt-1.5 text-sm text-slate-400">
        The strongest evidence is a cryptographic signature. Add a DigiLocker-issued or bank-signed PDF
        and we verify the issuer's signature, chained to the CCA-India root. No live pull: we check the
        signature on the file you provide. No signature? We fall through to forensic integrity checks.
      </p>

      <label htmlFor="src-file" className="mt-7 block cursor-pointer rounded-2xl border border-dashed border-hairline bg-surface-2/40 p-8 text-center transition hover:border-ink/40">
        <input id="src-file" type="file" accept="application/pdf,.pdf,image/*" className="hidden"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        <span className="gradient-text text-sm font-semibold">{file ? "Choose a different file" : "Add your statement"}</span>
        {file && <p className="mt-2 text-sm text-slate-300">{file.name}</p>}
      </label>

      {file && !needsPassword && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button onClick={onPull} disabled={pulling} className="btn-primary">
            {pulling ? "Verifying at source…" : "Verify at source"}
          </button>
          {source && (
            <span className={
              "glass inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-semibold " +
              (verified ? "" : status === "INVALID" ? "text-verdict-rejected" : "text-verdict-review")
            }>
              {verified ? <span className="gradient-text">✓ Verified at source</span>
                : status === "INVALID" ? "✕ Signature invalid (tampered)"
                  : status === "NOT_VERIFIED" ? "⚠ Signature valid, issuer not confirmed"
                    : "⚠ No signature — we’ll verify by forensics"}
            </span>
          )}
        </div>
      )}

      {needsPassword && (
        <PasswordPrompt
          value={password}
          onChange={onPassword}
          error={needsPassword.error}
          onSubmit={onPull}
          submitting={pulling}
        />
      )}

      {verified && source?.issuer && <p className="mt-2 text-sm text-slate-400">Issued by {source.issuer} · CCA-signed</p>}
      <p className="mt-4 text-xs text-slate-500">
        No verifiable source? You can still continue — we’ll verify the document’s internal logic next.
      </p>
    </div>
  );
}

// --- step 2: review ------------------------------------------------------------------------------

function Review({
  name, pan, entityType, source, fileName,
}: {
  name: string; pan: string; entityType: string | null; source: SourceResult | null; fileName: string | null;
}) {
  return (
    <div>
      <h2 className="text-2xl font-semibold text-slate-100">Review &amp; submit</h2>
      <p className="mt-1.5 text-sm text-slate-400">Confirm everything looks right. We’ll verify on submit.</p>
      <dl className="mt-7 divide-y divide-hairline rounded-2xl border border-hairline">
        <Row k="Applicant">{name}</Row>
        <Row k="PAN"><span className="font-mono">{pan}</span>{entityType && <span className="ml-2 text-xs text-slate-500">({entityType})</span>}</Row>
        <Row k="Document">{fileName ?? "—"}</Row>
        <Row k="Source verification">
          {source?.signature_status === "VERIFIED"
            ? <span className="gradient-text font-semibold">Verified at source{source.issuer ? ` · ${source.issuer}` : ""}</span>
            : <span className="text-slate-400">Will verify by forensics</span>}
        </Row>
      </dl>
    </div>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3.5">
      <dt className="text-sm text-slate-500">{k}</dt>
      <dd className="text-right text-sm font-medium text-slate-200">{children}</dd>
    </div>
  );
}

// --- step 3: decision ----------------------------------------------------------------------------

const VERDICT_UI: Record<string, { label: string; icon: string; line: string; danger?: boolean }> = {
  APPROVED: { label: "Verified", icon: "✓", line: "Your documents passed integrity checks." },
  REVIEW: { label: "Under review", icon: "⚠", line: "A bank officer will take a quick look." },
  REJECTED: { label: "Needs attention", icon: "✕", line: "We found an inconsistency in the document.", danger: true },
};

function Decision({ trust, onOpenConsole }: { trust: TrustScore; onOpenConsole: () => void }) {
  const v = VERDICT_UI[trust.verdict] ?? VERDICT_UI.REVIEW!;
  return (
    <div className="text-center">
      <div className={"mx-auto flex h-16 w-16 items-center justify-center rounded-full text-3xl " + (v.danger ? "bg-verdict-rejected-soft text-verdict-rejected" : "gradient-accent text-white shadow-card")}>
        {v.icon}
      </div>
      <h2 className="mt-4 text-2xl font-semibold text-slate-100">{v.label}</h2>
      <p className="mt-1 text-sm text-slate-400">{v.line}</p>

      <div className="glass mx-auto mt-7 max-w-xs rounded-3xl p-6">
        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Trust score</p>
        <p className="gradient-text mt-1 text-6xl font-semibold tnum">{trust.trust_score}</p>
        <p className="mt-1 text-xs text-slate-500">{trust.tier_reached.replace(/-/g, " ")}</p>
      </div>

      <p className="mt-6 text-sm text-slate-400">Reference {trust.session_id.slice(0, 12)}…</p>
      <button onClick={onOpenConsole} className="btn-gradient mt-6">
        Open in underwriter console →
      </button>
    </div>
  );
}
