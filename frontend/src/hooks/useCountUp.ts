import { useEffect, useRef, useState } from "react";

/**
 * Animate a number from 0 → target with an ease-out curve, honouring prefers-reduced-motion
 * (jumps straight to target when reduced motion is requested). Used for the trust-gauge sweep and
 * the numeric score readout. The TARGET is always the real backend value — only the tween is
 * cosmetic (CLAUDE.md §9 "no fabricated UI data").
 */
export function useCountUp(target: number, durationMs = 900): number {
  const [value, setValue] = useState(0);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReduced || durationMs <= 0) {
      setValue(target);
      return;
    }

    const start = performance.now();
    const from = 0;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3); // cubic ease-out
      setValue(from + (target - from) * eased);
      if (t < 1) {
        frame.current = requestAnimationFrame(tick);
      } else {
        setValue(target);
      }
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [target, durationMs]);

  return value;
}
