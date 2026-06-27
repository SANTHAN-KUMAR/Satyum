import { useEffect, useRef } from "react";

interface FrameSamplerOptions {
  videoRef: React.RefObject<HTMLVideoElement>;
  enabled: boolean;
  /** Cadence in ms — ~300ms windows, not every frame (CLAUDE.md §7 camera-path discipline). */
  intervalMs?: number;
  /** Longest edge of the downscaled frame sent to the server (bandwidth + privacy). */
  maxEdge?: number;
  /** Receives a base64 JPEG payload (without the data-URL prefix). */
  onFrame: (jpegBase64: string) => void;
}

/**
 * Samples downscaled JPEG frames from a live <video> at a fixed cadence and hands them to `onFrame`.
 * Backpressure-friendly by design: it samples on an interval rather than per-rAF, so it drops frames
 * instead of queueing unboundedly. Frames are produced only while `enabled`; nothing is persisted.
 */
export function useFrameSampler({
  videoRef,
  enabled,
  intervalMs = 300,
  maxEdge = 640,
  onFrame,
}: FrameSamplerOptions): void {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;

  useEffect(() => {
    if (!enabled) return;
    if (!canvasRef.current) canvasRef.current = document.createElement("canvas");
    const canvas = canvasRef.current;

    const id = window.setInterval(() => {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || video.videoWidth === 0) return;

      const scale = Math.min(1, maxEdge / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
      const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
      onFrameRef.current(base64);
    }, intervalMs);

    return () => window.clearInterval(id);
  }, [enabled, intervalMs, maxEdge, videoRef]);
}
