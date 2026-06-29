import { useState } from "react";
import { AppHeader } from "./components/AppHeader";
import { ModeTabs, type IntakeTab } from "./components/ModeTabs";
import { UploadIntake } from "./components/UploadIntake";
import { BundleIntake } from "./components/BundleIntake";
import { CameraCapture } from "./components/camera/CameraCapture";
import { SampleView } from "./components/SampleView";

export default function App() {
  const [tab, setTab] = useState<IntakeTab>("upload");

  return (
    <div className="flex min-h-full flex-col">
      <a
        href="#main"
        className="sr-only-focusable absolute left-3 top-3 z-50 rounded bg-accent px-3 py-1.5 text-sm font-semibold text-canvas"
      >
        Skip to content
      </a>
      <AppHeader />

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Verify a document</h2>
            <p className="text-sm text-slate-400">
              Upload a financial statement, cross-check a document bundle, run a live capture, or
              preview the console layout.
            </p>
          </div>
          <ModeTabs active={tab} onChange={setTab} />
        </div>

        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          className="animate-fade-in"
        >
          {tab === "upload" && <UploadIntake />}
          {tab === "bundle" && <BundleIntake />}
          {tab === "camera" && <CameraCapture />}
          {tab === "sample" && <SampleView />}
        </div>
      </main>

      <footer className="border-t border-hairline px-4 py-4 text-center text-xs text-slate-500 sm:px-6">
        Satyum — deterministic, auditable, fail-closed. No document content or camera frames are
        persisted.
      </footer>
    </div>
  );
}
