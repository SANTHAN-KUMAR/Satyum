import { AlertTriangle, Files, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { useVerifyBundle } from "@/hooks/useVerifyBundle";
import { ACCEPT_ATTR, formatBytes, rejectReason } from "@/lib/file";
import { cn } from "@/lib/cn";
import { BundleConsole } from "./evidence/BundleConsole";
import { StateMessage } from "./primitives/StateMessage";

/** Backend bounds (app/routes/verify.py :: _MIN_BUNDLE_DOCS / _MAX_BUNDLE_DOCS). */
const MIN_DOCS = 2;
const MAX_DOCS = 12;

/**
 * Multi-document bundle intake → POST /api/verify-bundle → BundleConsole (the cross-document graph).
 *
 * Holds the picked files locally (no previews round-tripped). Unlike single-document intake, the
 * underwriter assembles a set (statement + ID + deed…) and submits explicitly. Every state is
 * designed: empty, client-rejected, below-minimum, processing, backend error, and the bundle verdict.
 */
export function BundleIntake() {
  const [files, setFiles] = useState<File[]>([]);
  const [clientError, setClientError] = useState<string | null>(null);
  const [isDragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dragDepth = useRef(0);

  const verify = useVerifyBundle();

  const addFiles = useCallback(
    (incoming: File[]) => {
      if (incoming.length === 0) return;
      verify.reset();
      setClientError(null);
      setFiles((prev) => {
        const next = [...prev];
        for (const f of incoming) {
          const reason = rejectReason(f);
          if (reason) {
            setClientError(`${f.name}: ${reason}`);
            continue;
          }
          // De-dupe by name+size so a double-drop doesn't add the same file twice.
          if (next.some((e) => e.name === f.name && e.size === f.size)) continue;
          if (next.length >= MAX_DOCS) {
            setClientError(`A bundle holds at most ${MAX_DOCS} documents.`);
            break;
          }
          next.push(f);
        }
        return next;
      });
    },
    [verify],
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (e.dataTransfer.files) addFiles(Array.from(e.dataTransfer.files));
  };

  const removeAt = (idx: number) => {
    verify.reset();
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const clearAll = () => {
    setFiles([]);
    setClientError(null);
    verify.reset();
  };

  const canSubmit = files.length >= MIN_DOCS && !verify.isPending;

  return (
    <div className="space-y-5">
      {/* Dropzone. */}
      <div
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) setDragging(false);
        }}
        role="button"
        tabIndex={0}
        aria-label="Add documents to the bundle. Drag and drop PDFs or images here, or press Enter to browse."
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-9 text-center transition-colors",
          isDragging
            ? "border-accent bg-accent/5"
            : "border-hairline bg-surface/40 hover:border-accent/60 hover:bg-surface/70",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          multiple
          onChange={onInputChange}
          className="sr-only"
          aria-hidden="true"
          tabIndex={-1}
        />
        <span
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full border transition-colors",
            isDragging ? "border-accent text-accent" : "border-hairline text-slate-400 group-hover:text-accent",
          )}
          aria-hidden="true"
        >
          <Files size={22} strokeWidth={1.75} />
        </span>
        <div>
          <p className="text-sm font-semibold text-slate-100">
            {isDragging ? "Drop to add to the bundle" : "Add related documents (statement · ID · deed)"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {MIN_DOCS}–{MAX_DOCS} documents · cross-checked for one coherent identity · verified server-side
          </p>
        </div>
      </div>

      {/* Selected-file list. */}
      {files.length > 0 && (
        <div className="rounded-lg border border-hairline bg-surface/40">
          <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
            <span className="text-xs font-medium text-slate-300">
              {files.length} document{files.length === 1 ? "" : "s"} in bundle
              {files.length < MIN_DOCS && (
                <span className="ml-1 text-verdict-review">· add at least {MIN_DOCS - files.length} more</span>
              )}
            </span>
            <button
              type="button"
              onClick={clearAll}
              className="text-xs text-slate-400 hover:text-slate-200"
            >
              Clear all
            </button>
          </div>
          <ul className="divide-y divide-hairline">
            {files.map((f, i) => (
              <li key={`${f.name}-${f.size}`} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="truncate text-sm text-slate-200" title={f.name}>
                  {f.name} <span className="text-xs text-slate-500">({formatBytes(f.size)})</span>
                </span>
                <button
                  type="button"
                  onClick={() => removeAt(i)}
                  aria-label={`Remove ${f.name} from the bundle`}
                  className="shrink-0 rounded p-1 text-slate-500 hover:text-verdict-rejected"
                >
                  <X size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => verify.mutate({ files })}
          className={cn(
            "rounded-md px-4 py-2 text-sm font-semibold transition-colors",
            canSubmit
              ? "bg-accent text-canvas hover:bg-accent/90"
              : "cursor-not-allowed border border-hairline bg-surface-2 text-slate-500",
          )}
        >
          Verify bundle
        </button>
        {files.length > 0 && files.length < MIN_DOCS && (
          <span className="text-xs text-slate-500">A cross-document check needs at least {MIN_DOCS} documents.</span>
        )}
      </div>

      {clientError && (
        <StateMessage
          tone="error"
          title="That file can't be added"
          detail={clientError}
          icon={<AlertTriangle size={26} className="text-verdict-rejected" />}
        />
      )}

      {verify.isPending && (
        <StateMessage
          tone="loading"
          title="Verifying the bundle…"
          detail="Each document runs the full waterfall, then their identity fields are cross-checked. Processed in memory, never persisted."
        />
      )}

      {verify.isError && !verify.isPending && (
        <StateMessage
          tone="error"
          title="Bundle verification could not complete"
          detail={
            <>
              <p>{verify.error.message}</p>
              {verify.error instanceof ApiError && verify.error.status && (
                <p className="mt-1 font-mono text-xs text-slate-500">HTTP {verify.error.status}</p>
              )}
            </>
          }
          icon={<AlertTriangle size={26} className="text-verdict-rejected" />}
          action={
            <button
              type="button"
              onClick={() => verify.mutate({ files })}
              className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
            >
              Retry
            </button>
          }
        />
      )}

      {verify.isSuccess && <BundleConsole bundle={verify.data} />}
    </div>
  );
}
