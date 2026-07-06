import {
  MoveDown,
  MoveLeft,
  MoveRight,
  MoveUp,
  RotateCcw,
  RotateCw,
  ScanLine,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import type { ServerChallengeMessage } from "@/api/types";
import { cn } from "@/lib/cn";

interface ChallengeOverlayProps {
  challenge: ServerChallengeMessage | null;
  /** Has the real TTL clock started (via "Start attempt")? Before this, no countdown is shown —
   * reading the instruction and getting the document in frame is never raced against a deadline. */
  armed: boolean;
}

/** Directional icon for the active 3D challenge command (the instruction text is authoritative). */
const KIND_ICON: Record<string, LucideIcon> = {
  "tilt-left": MoveLeft,
  "tilt-right": MoveRight,
  "tilt-up": MoveUp,
  "tilt-down": MoveDown,
  "rotate-cw": RotateCw,
  "rotate-ccw": RotateCcw,
  "move-closer": ZoomIn,
  "move-away": ZoomOut,
};

/**
 * The icon physically moves the way the user should move the document, instead of only pulsing in
 * place — this is the direct fix for "how does the user understand tilt 22 degrees": a motion cue
 * needs no numeracy or literacy. Falls back to the plain pulse for an unrecognised kind.
 */
const KIND_ANIMATION: Record<string, string> = {
  "tilt-left": "animate-nudge-left",
  "tilt-right": "animate-nudge-right",
  "tilt-up": "animate-nudge-up",
  "tilt-down": "animate-nudge-down",
  "rotate-cw": "animate-nudge-rotate-cw",
  "rotate-ccw": "animate-nudge-rotate-ccw",
  "move-closer": "animate-nudge-zoom-in",
  "move-away": "animate-nudge-zoom-out",
};

/**
 * Overlays the SERVER-ISSUED active-challenge instruction on the live camera preview. Before the
 * attempt is armed (see `armed` prop), no countdown runs — this is the fix for a timer that used
 * to start the instant the instruction appeared, expiring before the user could even read it.
 * Renders nothing unless the server has actually issued a challenge — the instruction text is
 * never invented client-side (CLAUDE.md §3.1).
 */
export function ChallengeOverlay({ challenge, armed }: ChallengeOverlayProps) {
  const [remainingMs, setRemainingMs] = useState(0);

  useEffect(() => {
    if (!challenge || !armed) return;
    const tick = () => setRemainingMs(Math.max(0, challenge.expires_at_ms - Date.now()));
    tick();
    const id = window.setInterval(tick, 100);
    return () => window.clearInterval(id);
  }, [challenge, armed]);

  if (!challenge) return null;

  const expired = armed && remainingMs <= 0;
  const Icon = KIND_ICON[challenge.kind] ?? ScanLine;
  const motionClass = KIND_ANIMATION[challenge.kind] ?? "animate-pulse-ring";

  return (
    <div
      className="pointer-events-none absolute inset-x-0 top-0 flex justify-center p-3"
      role="status"
      aria-live="assertive"
    >
      <div
        className={cn(
          "flex items-center gap-3 rounded-lg border bg-canvas/85 px-4 py-2.5 backdrop-blur",
          expired ? "border-verdict-rejected/60" : "border-accent/60",
        )}
      >
        <span
          className={cn(expired ? "text-verdict-rejected" : cn(motionClass, "text-accent"))}
          aria-hidden="true"
        >
          <Icon size={26} strokeWidth={2} />
        </span>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-text-tertiary">
            Active challenge
          </p>
          <p className="text-sm font-semibold text-text-primary">{challenge.instruction}</p>
        </div>
        <span
          className={cn(
            "ml-2 rounded px-2 py-0.5 font-mono text-xs",
            expired ? "bg-verdict-rejected-soft text-verdict-rejected" : "bg-surface-muted text-text-secondary",
          )}
        >
          {!armed ? "get ready" : expired ? "expired" : `${(remainingMs / 1000).toFixed(1)}s`}
        </span>
      </div>
    </div>
  );
}
