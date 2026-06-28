/**
 * Typed API client for the Satyum backend.
 *
 * The ONLY place the frontend talks to the network. Endpoints are relative (same-origin) so the
 * Vite dev proxy / production Nginx decides the real backend origin — no hardcoded URLs (CLAUDE.md
 * §5/§11). Responses are validated at the boundary (guards.ts) before any component sees them.
 */

import { parseTrustScore } from "./guards";
import type { TrustScore } from "./types";

/** Relative endpoints. Same-origin → resolved by the dev proxy (vite.config.ts) or Nginx in prod. */
export const ENDPOINTS = {
  verify: "/api/verify",
  /** WebSocket path; the scheme/host are derived from window.location at connect time. */
  liveVerify: "/ws/verify",
} as const;

/** A network or backend failure surfaced honestly to the UI (never swallowed — CLAUDE.md §5). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface VerifyOptions {
  /** Optional underwriter-declared document type, forwarded as a form field if present. */
  docType?: string;
  /** Lets a caller (and TanStack Query) cancel an in-flight upload. */
  signal?: AbortSignal;
}

/**
 * POST /api/verify (multipart/form-data) → TrustScore (including .evidence_pack).
 *
 * The backend treats the uploaded file as hostile and runs the full verification waterfall;
 * we send the raw bytes under the form field `file`.
 */
export async function verifyDocument(file: File, opts: VerifyOptions = {}): Promise<TrustScore> {
  const form = new FormData();
  form.append("file", file, file.name);
  if (opts.docType) form.append("doc_type", opts.docType);

  let res: Response;
  try {
    res = await fetch(ENDPOINTS.verify, {
      method: "POST",
      body: form,
      headers: { Accept: "application/json" },
      signal: opts.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    // No HTTP response at all → the backend is unreachable. Say so plainly.
    throw new ApiError(
      "Could not reach the verification service. Confirm the backend is running and reachable.",
    );
  }

  if (!res.ok) {
    // Surface the backend's own error detail when it gives one (FastAPI's {"detail": ...}).
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — fall through with just the status */
    }
    throw new ApiError(
      detail ?? `Verification failed (HTTP ${res.status}).`,
      res.status,
      detail,
    );
  }

  let json: unknown;
  try {
    json = await res.json();
  } catch {
    throw new ApiError("Verification service returned a non-JSON response.");
  }

  // Validate the wire shape before any component renders it (CLAUDE.md §4).
  return parseTrustScore(json);
}

/** Build the absolute ws(s):// URL for the live-capture socket from the current page origin. */
export function liveVerifyUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${ENDPOINTS.liveVerify}`;
}
