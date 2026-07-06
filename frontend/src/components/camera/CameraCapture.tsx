import {
  AlertTriangle,
  Ban,
  Camera,
  CameraOff,
  CheckCheck,
  MonitorOff,
  Play,
  ScanLine,
  Square,
  Timer,
} from "lucide-react";
import { useEffect, useRef } from "react";
import { useCamera } from "@/hooks/useCamera";
import { useVerifySocket } from "@/hooks/useVerifysocket";
import { useFrameSampler } from "@/hooks/useFrameSampler";
import { Panel } from "@/components/primitives/Panel";
import { StateMessage } from "@/components/primitives/StateMessage";
import { EvidenceConsole } from "@/components/evidence/EvidenceConsole";
import { ChallengeOverlay } from "./ChallengeOverlay";
import { ChallengeGuidance } from "./ChallengeGuidance";
import { LiveTierStatus } from "./LiveTierStatus";
import { ConnectionBadge } from "./ConnectionBadge";

interface CameraCaptureProps {
  /** Optional declared document type, forwarded in the WS hello. */
  docType?: string | null;
}

/**
 * Tier-3 live capture (CLAUDE.md §1 / §9): a real getUserMedia WebRTC preview plus a native
 * WebSocket client to /ws/verify that streams downscaled frames and renders the server's
 * active-challenge instruction overlay and live per-tier status.
 *
 * Wired for REAL. Camera permission/no-device/unsupported states are all designed; the socket
 * reports its true connection state. If the live-capture backend isn't available, the user sees an
 * honest "unreachable" state and NO fabricated challenge or signal data ever appears.
 */
export function CameraCapture({ docType = null }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const camera = useCamera();
  const socket = useVerifySocket();

  // Attach / detach the live stream to the <video> element.
  useEffect(() => {
    const video = videoRef.current;
    if (video && camera.stream) {
      video.srcObject = camera.stream;
    }
    return () => {
      if (video) video.srcObject = null;
    };
  }, [camera.stream]);

  // Stream frames only while the camera is live AND the socket is open.
  const streaming = camera.state === "live" && socket.state === "open";
  useFrameSampler({
    videoRef,
    enabled: streaming,
    onFrame: socket.sendFrame,
  });

  const startSession = async () => {
    await camera.start();
    socket.connect(docType);
  };

  const stopSession = () => {
    socket.disconnect();
    camera.stop();
  };

  // Release everything on unmount (privacy: frames are session-only, never persisted — §10).
  useEffect(() => {
    return () => {
      socket.disconnect();
      camera.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showPreview = camera.state === "live" || camera.state === "requesting";

  // The active-challenge signal on the LATEST scored attempt, and whether it cleanly passed —
  // mirrors the analyzer's own PASS threshold (backend/app/routes/verify.py :: _challenge_passed).
  const activeSignal = socket.result?.signals.find((s) => s.name === "active_challenge");
  const challengePassed =
    activeSignal != null && activeSignal.suspicion !== null && activeSignal.suspicion <= 0.1;
  const retriesRemaining = socket.challenge?.retries_remaining ?? null;
  // Only render the evidence console once the outcome is truly final — a clean pass, or retries
  // exhausted — so the underwriter-facing verdict never appears while an in-session retry is still on
  // offer (that would read as final when it isn't).
  const showEvidenceConsole =
    socket.result != null && (challengePassed || !retriesRemaining);

  return (
    <div className="space-y-4">
      <Panel
        title="Live capture · Tier 3"
        icon={ScanLine}
        aside={<ConnectionBadge state={socket.state} />}
        bodyClassName="space-y-4"
      >
        <p className="text-sm text-text-tertiary">
          For wet-ink, contested, or un-sourceable documents. The server issues an unpredictable
          physical challenge and verifies the document's tracked motion — defeating photo-of-screen
          and pre-recorded replay. Frames are processed in memory only and never persisted.
        </p>

        {/* Preview surface — every camera state is designed. */}
        <div className="relative overflow-hidden rounded-lg border border-hairline bg-black">
          {showPreview ? (
            <>
              {/* Live, muted, audio-less camera preview — captions are not applicable. */}
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="block aspect-video w-full bg-black object-cover"
                aria-label="Live camera preview"
              />
              <ChallengeOverlay challenge={socket.challenge} armed={socket.armed} />
              {camera.state === "requesting" && (
                <div className="absolute inset-0 flex items-center justify-center bg-canvas/60 text-sm text-text-secondary">
                  Waiting for camera permission…
                </div>
              )}
            </>
          ) : (
            <div className="grid aspect-video w-full place-items-center p-4">
              <CameraPlaceholder state={camera.state} error={camera.error} onStart={startSession} />
            </div>
          )}
        </div>

        {/* Controls. */}
        <div className="flex flex-wrap items-center gap-2">
          {camera.state !== "live" ? (
            <button
              type="button"
              onClick={startSession}
              disabled={camera.state === "requesting" || camera.state === "unsupported"}
              className="inline-flex items-center gap-2 rounded-md border border-accent/50 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Play size={15} aria-hidden="true" />
              Start live session
            </button>
          ) : (
            <>
              {socket.armed ? (
                <button
                  type="button"
                  onClick={socket.requestScore}
                  disabled={!streaming}
                  className="inline-flex items-center gap-2 rounded-md border border-accent/50 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <CheckCheck size={15} aria-hidden="true" />
                  Verify now
                </button>
              ) : (
                <button
                  type="button"
                  onClick={socket.startAttempt}
                  disabled={!streaming || !socket.challenge}
                  className="inline-flex items-center gap-2 rounded-md border border-accent/50 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Timer size={15} aria-hidden="true" />
                  Start attempt
                </button>
              )}
              <button
                type="button"
                onClick={stopSession}
                className="inline-flex items-center gap-2 rounded-md border border-verdict-rejected/50 bg-verdict-rejected-soft px-4 py-2 text-sm font-semibold text-verdict-rejected hover:bg-verdict-rejected/20"
              >
                <Square size={14} aria-hidden="true" />
                End session
              </button>
            </>
          )}
          {socket.notice && (
            <span className="text-xs text-text-tertiary" role="status">
              {socket.notice}
            </span>
          )}
        </div>
      </Panel>

      {/* Live per-tier status while streaming. */}
      <LiveTierStatus signals={socket.liveSignals} streaming={streaming} />

      {/* Plain-language, retryable guidance for the person performing the challenge — separate from
          the technical evidence console below (CLAUDE.md §9). */}
      {socket.result && (
        <ChallengeGuidance
          result={socket.result}
          retriesRemaining={retriesRemaining}
          onRetry={socket.retry}
        />
      )}

      {/* The final verdict, once the session outcome is truly final (pass, or retries exhausted). */}
      {showEvidenceConsole && socket.result && (
        <EvidenceConsole
          trust={socket.result}
          previewUrl={null}
          isPdf={false}
          fileName={`live-capture · ${socket.result.session_id}`}
        />
      )}
    </div>
  );
}

interface PlaceholderProps {
  state: ReturnType<typeof useCamera>["state"];
  error: string | null;
  onStart: () => void;
}

/** The designed no-camera / denied / unsupported / error states for the preview surface. */
function CameraPlaceholder({ state, error, onStart }: PlaceholderProps) {
  if (state === "unsupported") {
    return (
      <StateMessage
        tone="error"
        title="Camera not available in this context"
        detail="getUserMedia requires a secure origin (https or localhost) and a browser with camera support."
        icon={<MonitorOff size={28} className="text-verdict-rejected" />}
      />
    );
  }
  if (state === "denied") {
    return (
      <StateMessage
        tone="error"
        title="Camera permission denied"
        detail={error ?? "Grant camera access in your browser's site settings, then start again."}
        icon={<Ban size={28} className="text-verdict-rejected" />}
        action={
          <button
            type="button"
            onClick={onStart}
            className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
          >
            Try again
          </button>
        }
      />
    );
  }
  if (state === "no-device") {
    return (
      <StateMessage
        tone="error"
        title="No camera found"
        detail={error ?? "Connect a camera and try again."}
        icon={<CameraOff size={28} className="text-verdict-rejected" />}
      />
    );
  }
  if (state === "error") {
    return (
      <StateMessage
        tone="error"
        title="Camera could not start"
        detail={error ?? "An unexpected camera error occurred."}
        icon={<AlertTriangle size={28} className="text-verdict-rejected" />}
        action={
          <button
            type="button"
            onClick={onStart}
            className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
          >
            Retry
          </button>
        }
      />
    );
  }
  // idle
  return (
    <StateMessage
      tone="info"
      title="Live capture is off"
      detail="Start a session to open the camera and stream to the verification pipeline."
      icon={<Camera size={28} className="text-accent" />}
      action={
        <button
          type="button"
          onClick={onStart}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
        >
          Start live session
        </button>
      }
    />
  );
}
