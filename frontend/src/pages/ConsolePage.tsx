import { useState } from "react";
import { ModeTabs, type IntakeTab } from "@/components/ModeTabs";
import { UploadIntake } from "@/components/UploadIntake";
import { BundleIntake } from "@/components/BundleIntake";
import { CameraCapture } from "@/components/camera/CameraCapture";
import { SampleView } from "@/components/SampleView";
import { EvidenceConsole } from "@/components/evidence/EvidenceConsole";
import { getLastCase } from "@/lib/lastResult";

/**
 * The Underwriter Console — the application an onboarded case flows into. If onboarding just handed off
 * a verified case, show its evidence console first; otherwise (or on "verify another") the full intake
 * workspace (upload / bundle / live capture / sample).
 */
export function ConsolePage() {
  const handed = getLastCase();
  const [showHanded, setShowHanded] = useState(Boolean(handed));
  const [tab, setTab] = useState<IntakeTab>("upload");

  if (handed && showHanded) {
    return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-slate-100">Underwriter console</h1>
            <p className="text-sm text-slate-500">Case handed off from onboarding · {handed.fileName}</p>
          </div>
          <button onClick={() => setShowHanded(false)} className="btn-ghost">
            Verify another document
          </button>
        </div>
        <EvidenceConsole
          trust={handed.trust}
          previewUrl={handed.previewUrl}
          isPdf={handed.isPdf}
          fileName={handed.fileName}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Underwriter console</h1>
          <p className="text-sm text-slate-500">
            Verify a document, cross-check a bundle, run a live capture, or preview the console.
          </p>
        </div>
        <ModeTabs active={tab} onChange={setTab} />
      </div>
      <div role="tabpanel" className="animate-fade-in">
        {tab === "upload" && <UploadIntake />}
        {tab === "bundle" && <BundleIntake />}
        {tab === "camera" && <CameraCapture />}
        {tab === "sample" && <SampleView />}
      </div>
    </div>
  );
}
