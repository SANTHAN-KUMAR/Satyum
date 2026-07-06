/**
 * Typed API client for the Satyum backend.
 *
 * The ONLY place the frontend talks to the network. Endpoints are relative (same-origin) so the
 * Vite dev proxy / production Nginx decides the real backend origin — no hardcoded URLs (CLAUDE.md
 * §5/§11). Responses are validated at the boundary (guards.ts) before any component sees them.
 */

import { parseBundleTrustScore, parseTrustScore } from "./guards";
import type { BundleTrustScore, TrustScore } from "./types";

/**
 * Optional absolute backend origin for a SPLIT deploy (e.g. a Vercel frontend → a Railway backend).
 * Set `VITE_API_BASE_URL=https://your-backend.up.railway.app` at build time. When empty, endpoints are
 * RELATIVE/same-origin — resolved by the Vite dev proxy, an Nginx reverse proxy, or a Vercel rewrite.
 * Trailing slash trimmed so `${base}/api/...` never double-slashes.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** Endpoint paths (relative). Use {@link apiUrl} to resolve against the optional split-deploy base. */
export const ENDPOINTS = {
  verify: "/api/verify",
  /** Multi-document bundle → the cross-document consistency graph (ADR-003 #3). */
  verifyBundle: "/api/verify-bundle",
  /** WebSocket path; the scheme/host are derived from the API base or window.location at connect time. */
  liveVerify: "/ws/verify",
} as const;

/** Resolve an endpoint path against the optional split-deploy base (absolute in prod, relative else). */
export function apiUrl(path: string): string {
  return API_BASE + path;
}

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

/** Backend health (GET /api/health) — used by the UI to show whether the backend is reachable. */
export interface HealthInfo {
  status: string;
  analyzers: number;
  audit_backend: string;
  audit_chain_intact: boolean;
}

export async function getHealth(signal?: AbortSignal): Promise<HealthInfo> {
  const res = await fetch(apiUrl("/api/health"), { headers: { Accept: "application/json" }, signal });
  if (!res.ok) throw new ApiError(`backend health HTTP ${res.status}`);
  return (await res.json()) as HealthInfo;
}

interface VerifyOptions {
  /** Optional underwriter-declared document type, forwarded as a form field if present. */
  docType?: string;
  /** Optional engineered application features, sent as `features_json` for promoted-rule evaluation. */
  features?: Record<string, unknown>;
  /** Optional applicant-entered PAN. The backend cross-checks it against the document's PAN. */
  claimedPan?: string;
  /** Optional applicant-entered name. Soft fallback identity check: PAN stays authoritative when
   *  present, but this is the only cross-check available for a document with no PAN at all (a land
   *  deed / encumbrance certificate) — without it that class of document had no identity check
   *  whatsoever (backend forensics/claimed_identity.py). */
  claimedName?: string;
  /** Password for an encrypted (password-protected) PDF. The backend decrypts it in memory so the
   *  original signed bytes are never re-saved, preserving the signature. */
  password?: string;
  /** Accrue this document's extracted identity claims into an application case, strengthening the
   *  cross-document corroboration graph. */
  caseId?: string;
  /** Lets a caller (and TanStack Query) cancel an in-flight upload. */
  signal?: AbortSignal;
}

/**
 * Raised when the uploaded PDF is password-protected and needs an in-app password. This is a
 * recoverable prompt, not a verification failure: the caller shows a password field and retries with
 * `verifyDocument(file, { password })`.
 */
export class PasswordRequiredError extends Error {
  /** Set when a supplied password was incorrect (so the UI can show "wrong password, try again"). */
  readonly passwordError?: string;
  constructor(message: string, passwordError?: string) {
    super(message);
    this.name = "PasswordRequiredError";
    this.passwordError = passwordError;
  }
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
  if (opts.features) form.append("features_json", JSON.stringify(opts.features));
  if (opts.claimedPan) form.append("claimed_pan", opts.claimedPan);
  if (opts.claimedName) form.append("claimed_name", opts.claimedName);
  if (opts.password) form.append("pdf_password", opts.password);
  if (opts.caseId) form.append("case_id", opts.caseId);

  let res: Response;
  try {
    // 180-second client-side timeout so the UI doesn't hang forever if the backend VLM API hangs
    const fetchSignal = opts.signal || AbortSignal.timeout(180000);
    res = await fetch(apiUrl(ENDPOINTS.verify), {
      method: "POST",
      body: form,
      headers: { Accept: "application/json" },
      signal: fetchSignal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "TimeoutError") {
      throw new ApiError(
        "Verification timed out. The backend AI provider (Cloudflare/Groq) might be rate-limited or unresponsive. Please check the backend terminal."
      );
    }
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

  // An encrypted PDF returns a recoverable prompt instead of a verdict. Surface it as a typed error.
  if (json && typeof json === "object" && (json as { needs_password?: unknown }).needs_password === true) {
    const body = json as { reason?: string; password_error?: string };
    throw new PasswordRequiredError(
      body.reason ?? "This document is password-protected. Enter its password to continue.",
      body.password_error,
    );
  }

  // Validate the wire shape before any component renders it (CLAUDE.md §4).
  return parseTrustScore(json);
}

/**
 * POST /api/verify-bundle (multipart/form-data, repeated `files`) → BundleTrustScore.
 *
 * Sends 2–12 related documents (statement / ID / deed) under the repeated form field `files`. The
 * backend verifies each independently AND cross-checks their extracted identity fields, returning
 * the per-document trust scores plus the cross-document consistency signal (ADR-003 #3).
 */
export async function verifyBundle(
  files: File[],
  opts: { signal?: AbortSignal } = {},
): Promise<BundleTrustScore> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);

  let res: Response;
  try {
    // 180-second client-side timeout so the UI doesn't hang forever if the backend VLM API hangs
    const fetchSignal = opts.signal || AbortSignal.timeout(180000);
    res = await fetch(apiUrl(ENDPOINTS.verifyBundle), {
      method: "POST",
      body: form,
      headers: { Accept: "application/json" },
      signal: fetchSignal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "TimeoutError") {
      throw new ApiError(
        "Verification timed out. The backend AI provider (Cloudflare/Groq) might be rate-limited or unresponsive. Please check the backend terminal."
      );
    }
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(
      "Could not reach the verification service. Confirm the backend is running and reachable.",
    );
  }

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — fall through with just the status */
    }
    throw new ApiError(detail ?? `Bundle verification failed (HTTP ${res.status}).`, res.status, detail);
  }

  let json: unknown;
  try {
    json = await res.json();
  } catch {
    throw new ApiError("Verification service returned a non-JSON response.");
  }
  return parseBundleTrustScore(json);
}

/**
 * Build the absolute ws(s):// URL for the live-capture socket. In a split deploy the WebSocket cannot
 * go through an HTTP-only proxy/rewrite, so when an absolute API base is configured we connect the
 * socket DIRECTLY to that backend host; otherwise we use the current page origin (dev proxy / Nginx).
 */
export function liveVerifyUrl(): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, "ws") + ENDPOINTS.liveVerify;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${ENDPOINTS.liveVerify}`;
}
