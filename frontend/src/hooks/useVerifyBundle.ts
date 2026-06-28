import { useMutation } from "@tanstack/react-query";
import { verifyBundle } from "@/api/client";
import type { BundleTrustScore } from "@/api/types";

interface VerifyBundleVars {
  files: File[];
}

/**
 * TanStack Query mutation wrapping POST /api/verify-bundle. Returns the typed BundleTrustScore so the
 * bundle intake renders real loading / error / success state — never a fabricated cross-document
 * result. Like single-document verify, it does NOT retry: a verdict must not be silently re-run.
 */
export function useVerifyBundle() {
  return useMutation<BundleTrustScore, Error, VerifyBundleVars>({
    mutationKey: ["verify-bundle"],
    mutationFn: ({ files }) => verifyBundle(files),
    retry: false,
  });
}
