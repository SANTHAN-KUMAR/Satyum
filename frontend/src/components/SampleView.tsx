import { FlaskConical } from "lucide-react";
import { SAMPLE_TRUST_SCORE } from "@/fixtures/sampleTrustScore";
import { EvidenceConsole } from "./evidence/EvidenceConsole";

/**
 * A Storybook-style local preview of the EvidenceConsole rendered against the SAMPLE fixture, so the
 * layout can be reviewed without a running backend. The banner makes it UNMISTAKABLE that this is
 * sample data — it is never shown on the real FILE/CAMERA paths (CLAUDE.md §9).
 */
export function SampleView() {
  return (
    <div className="space-y-4">
      <div
        role="note"
        className="flex items-center gap-2.5 rounded-lg border border-dashed border-verdict-review/60 bg-verdict-review-soft px-4 py-2.5 text-sm text-verdict-review"
      >
        <FlaskConical size={16} className="shrink-0" aria-hidden="true" />
        <span>
          <strong>Sample data.</strong> This view renders a hand-authored fixture to preview the
          console layout offline. It is <em>not</em> a real verification result.
        </span>
      </div>
      <EvidenceConsole
        trust={SAMPLE_TRUST_SCORE}
        previewUrl={null}
        isPdf
        // Prefixed so the global Copilot drawer's "Analyzing …" header can't be mistaken for a real
        // result once this registers as the drawer's active context (CLAUDE.md §9).
        fileName="[SAMPLE] sample-statement.pdf"
      />
    </div>
  );
}
