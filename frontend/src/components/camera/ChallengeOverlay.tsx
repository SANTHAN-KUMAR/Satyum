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
 * Overlays the SERVER-ISSUED active-challenge instruction on the live camera preview, with a live
 * countdown to the challenge's time-bounded nonce expiry. Renders nothing unless the server has
 * actually issued a challenge — the instruction text is never invented client-side (CLAUDE.md §3.1).
 */
export function ChallengeOverlay({ challenge }: ChallengeOverlayProps) {
  const [remainingMs, setRemainingMs] = useState(0);

  useEffect(() => {
    if (!challenge) return;
    const tick = () => setRemainingMs(Math.max(0, challenge.expires_at_ms - Date.now()));
    tick();
    const id = window.setInterval(tick, 100);
    return () => window.clearInterval(id);
  }, [challenge]);

  if (!challenge) return null;

  const expired = remainingMs <= 0;
  const Icon = KIND_ICON[challenge.kind] ?? ScanLine;

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
          className={cn(expired ? "text-verdict-rejected" : "animate-pulse-ring text-accent")}
          aria-hidden="true"
        >
          <Icon size={26} strokeWidth={2} />
        </span>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            Active challenge
          </p>
          <p className="text-sm font-semibold text-slate-100">{challenge.instruction}</p>
        </div>
        <span
          className={cn(
            "ml-2 rounded px-2 py-0.5 font-mono text-xs",
            expired ? "bg-verdict-rejected-soft text-verdict-rejected" : "bg-surface-2 text-slate-300",
          )}
        >
          {expired ? "expired" : `${(remainingMs / 1000).toFixed(1)}s`}
        </span>
      </div>
    </div>
  );
}
