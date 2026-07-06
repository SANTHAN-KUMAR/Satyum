import { AlertTriangle, CheckCircle2, RotateCcw } from "lucide-react";
import type { TrustScore } from "@/api/types";
import { cn } from "@/lib/cn";

interface ChallengeGuidanceProps {
  result: TrustScore | null;
  retriesRemaining: number | null;
  onRetry: () => void;
}

/**
 * Plain-language guidance for the PERSON performing the live challenge — separate from
 * ReasonsCard/the underwriter evidence console, which stay verbatim/technical (CLAUDE.md §9). This
 * component translates `active_challenge`'s `measurements.reason_code` (backend/capture/challenge.py)
 * into one sentence a non-technical user can act on, plus a same-session retry — never inventing a
 * reason of its own (CLAUDE.md §3.1: every sentence maps 1:1 to a real reason_code the analyzer emitted).
 */
const REASON_COPY: Record<string, string> = {
  live_ok: "Motion confirmed — this looks like a real physical document.",
  live_ok_scripted_suspected:
    "Motion matched, but it looked too mechanically smooth to be a natural hand movement.",
  inconsistent_homography:
    "We couldn't confirm this is a real physical document in front of the camera — the motion looked like it came from a flat screen or photo, not a physical page.",
  wrong_axis: "You moved the document, but not in the direction that was asked for.",
  wrong_magnitude: "Good direction, but the movement didn't match what was asked for.",
};

function magnitudeHint(measurements: Record<string, unknown>): string | null {
  const needsMore = measurements.needs_more_or_less;
  if (needsMore === "more") return "Try tilting further this time.";
  if (needsMore === "less") return "Try a smaller, gentler tilt this time.";
  return null;
}

export function ChallengeGuidance({ result, retriesRemaining, onRetry }: ChallengeGuidanceProps) {
  if (!result) return null;
  const signal = result.signals.find((s) => s.name === "active_challenge");
  if (!signal) return null;

  const reasonCode = typeof signal.measurements.reason_code === "string"
    ? signal.measurements.reason_code
    : null;
  const passed = signal.suspicion !== null && signal.suspicion <= 0.1;

  if (passed) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-hairline bg-surface-2 px-4 py-3 text-sm text-text-secondary">
        <CheckCircle2 size={18} className="text-verdict-approved" aria-hidden="true" />
        <span>{reasonCode ? REASON_COPY[reasonCode] : "Motion confirmed."}</span>
      </div>
    );
  }

  const canRetry = retriesRemaining !== null && retriesRemaining > 0;
  const copy = (reasonCode && REASON_COPY[reasonCode]) ?? "The physical-motion challenge wasn't matched.";
  const hint = magnitudeHint(signal.measurements);

  return (
    <div
      className={cn(
        "space-y-2 rounded-lg border border-verdict-rejected/40 bg-verdict-rejected-soft px-4 py-3 text-sm",
      )}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-verdict-rejected" aria-hidden="true" />
        <div className="space-y-1">
          <p className="font-medium text-verdict-rejected">{copy}</p>
          {hint && <p className="text-text-secondary">{hint}</p>}
        </div>
      </div>
      {canRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-md border border-accent/50 bg-canvas px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/10"
        >
          <RotateCcw size={13} aria-hidden="true" />
          Try the challenge again ({retriesRemaining} attempt{retriesRemaining === 1 ? "" : "s"} left)
        </button>
      ) : (
        <p className="text-xs text-text-tertiary">
          No more attempts left this session — this result stands and the case goes to review.
        </p>
      )}
    </div>
  );
}
