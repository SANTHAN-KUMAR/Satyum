import { useMutation } from "@tanstack/react-query";
import { verifyDocument } from "@/api/client";
import type { TrustScore } from "@/api/types";

interface VerifyVars {
  file: File;
  docType?: string;
}

/**
 * TanStack Query mutation wrapping POST /api/verify. Exposes typed { trustScore, isPending, error }
 * so the intake component renders loading / error / success states from real request state — never a
 * faked result.
 */
export function useVerifyDocument() {
  return useMutation<TrustScore, Error, VerifyVars>({
    mutationKey: ["verify"],
    mutationFn: ({ file, docType }) => verifyDocument(file, docType ? { docType } : {}),
    retry: false, // a verification verdict must not be silently retried — surface failures honestly
  });
}
