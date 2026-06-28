/**
 * Client-side intake guards. These mirror the backend's safe-ingestion limits (CLAUDE.md §10) so we
 * fail fast with a clear message instead of round-tripping a too-large/unsupported file — but they
 * are a UX convenience, NOT the security boundary. The backend re-validates every uploaded file as
 * hostile; the client check never decides trust.
 */

// Mirrors backend/app/config.py :: max_file_bytes (25 MiB).
export const MAX_FILE_BYTES = 25 * 1024 * 1024;

// The primary path is financial statements as PDF; signed/scanned images are accepted too.
export const ACCEPTED_MIME = [
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/tiff",
] as const;

export const ACCEPT_ATTR = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,application/pdf,image/*";

export function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export function isPreviewableImage(file: File): boolean {
  return file.type.startsWith("image/");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let val = bytes / 1024;
  let unit = 0;
  while (val >= 1024 && unit < units.length - 1) {
    val /= 1024;
    unit += 1;
  }
  return `${val.toFixed(val < 10 ? 1 : 0)} ${units[unit]}`;
}

/** Returns null when acceptable, or a human-readable rejection reason. */
export function rejectReason(file: File): string | null {
  const okType =
    (ACCEPTED_MIME as readonly string[]).includes(file.type) ||
    isPdf(file) ||
    file.type.startsWith("image/");
  if (!okType) {
    return `Unsupported file type "${file.type || "unknown"}". Upload a PDF or an image.`;
  }
  if (file.size > MAX_FILE_BYTES) {
    return `File is ${formatBytes(file.size)} — exceeds the ${formatBytes(MAX_FILE_BYTES)} limit.`;
  }
  if (file.size === 0) {
    return "File is empty.";
  }
  return null;
}
