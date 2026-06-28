import { useCallback, useEffect, useRef, useState } from "react";

/**
 * getUserMedia camera lifecycle with every real state modelled honestly (CLAUDE.md §9: no-camera,
 * permission-denied, and error states are all designed — never a raw browser exception).
 *
 *  - "idle"        : not yet requested
 *  - "unsupported" : the browser/context has no mediaDevices (e.g. non-secure origin)
 *  - "requesting"  : permission prompt in flight
 *  - "live"        : a MediaStream is attached
 *  - "denied"      : the user blocked camera access
 *  - "no-device"   : permission ok but no camera present
 *  - "error"       : any other getUserMedia failure (surfaced, not swallowed)
 */
export type CameraState =
  | "idle"
  | "unsupported"
  | "requesting"
  | "live"
  | "denied"
  | "no-device"
  | "error";

interface UseCameraResult {
  state: CameraState;
  stream: MediaStream | null;
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
}

const isSupported = (): boolean =>
  typeof navigator !== "undefined" &&
  !!navigator.mediaDevices &&
  typeof navigator.mediaDevices.getUserMedia === "function";

export function useCamera(): UseCameraResult {
  const [state, setState] = useState<CameraState>(() => (isSupported() ? "idle" : "unsupported"));
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

  const stop = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setStream(null);
    setState((s) => (s === "unsupported" ? s : "idle"));
  }, []);

  const start = useCallback(async () => {
    if (!isSupported()) {
      setState("unsupported");
      return;
    }
    setError(null);
    setState("requesting");
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = media;
      setStream(media);
      setState("live");
    } catch (err) {
      // Map the real DOMException names to honest, captioned states.
      const name = err instanceof DOMException ? err.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setState("denied");
        setError("Camera permission was denied. Grant access in your browser's site settings to continue.");
      } else if (name === "NotFoundError" || name === "OverconstrainedError") {
        setState("no-device");
        setError("No camera device was found on this machine.");
      } else if (name === "NotReadableError") {
        setState("error");
        setError("The camera is in use by another application and could not be opened.");
      } else {
        setState("error");
        setError(err instanceof Error ? err.message : "The camera could not be started.");
      }
    }
  }, []);

  // Always release the camera on unmount — frames live only for the session (CLAUDE.md §10).
  useEffect(() => stop, [stop]);

  return { state, stream, error, start, stop };
}
