import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { OnboardingFlow } from "./pages/onboarding/OnboardingFlow";
import { ConsolePage } from "./pages/ConsolePage";
import { ConsortiumPage } from "./pages/ConsortiumPage";
import { IntelligencePage } from "./pages/IntelligencePage";

/**
 * Routes. The applicant ONBOARDING flow is a clean, full-screen journey (its own layout); the
 * underwriter-facing surfaces (console, consortium simulator, master model) share the app shell.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/onboarding" replace />} />
      <Route path="/onboarding/*" element={<OnboardingFlow />} />
      <Route element={<AppShell />}>
        <Route path="/console" element={<ConsolePage />} />
        <Route path="/consortium" element={<ConsortiumPage />} />
        <Route path="/model" element={<IntelligencePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/onboarding" replace />} />
    </Routes>
  );
}
