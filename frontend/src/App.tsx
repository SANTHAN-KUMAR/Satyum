import { useState } from "react";
import { AppHeader } from "./components/AppHeader";
import { ModeTabs, type IntakeTab } from "./components/ModeTabs";
import { UploadIntake } from "./components/UploadIntake";
import { BundleIntake } from "./components/BundleIntake";
import { CameraCapture } from "./components/camera/CameraCapture";
import { SampleView } from "./components/SampleView";
import { COPY } from "@/lib/copy";

export default function App() {
  const [tab, setTab] = useState<IntakeTab>("upload");

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <a
        href="#main"
        className="sr-only-focusable absolute left-3 top-3 z-50 rounded bg-accent px-3 py-1.5 text-sm font-semibold text-canvas"
      >
        Skip to content
      </a>
      <AppHeader />

      <div className="flex flex-1 flex-col sm:flex-row">
        {/* Sidebar Navigation */}
        <aside className="border-b border-hairline bg-surface-muted/30 px-4 py-3 sm:w-64 sm:shrink-0 sm:border-b-0 sm:border-r sm:p-6">
          <ModeTabs active={tab} onChange={setTab} />
        </aside>

        {/* Main Content Area */}
        <main id="main" className="flex-1 overflow-y-auto px-4 py-8 sm:px-10 lg:px-12">
          <div className="mx-auto max-w-5xl">
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
          </div>
        </main>
      </div>

      <footer className="border-t border-hairline bg-canvas px-4 py-5 text-center text-xs text-text-tertiary sm:px-6">
        {COPY.FOOTER_SECURE}
      </footer>
    </div>
  );
}
