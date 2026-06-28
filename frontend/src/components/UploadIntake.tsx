import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { useVerifyDocument } from "@/hooks/useVerifyDocument";
import { ACCEPT_ATTR, formatBytes, isPdf, isPreviewableImage, rejectReason } from "@/lib/file";
import { cn } from "@/lib/cn";
import { EvidenceConsole } from "./evidence/EvidenceConsole";
import { StateMessage } from "./primitives/StateMessage";

interface SelectedFile {
  file: File;
  previewUrl: string | null; // object URL for images; null for PDFs
  isPdf: boolean;
}

/**
 * File-upload intake (drag/drop or browse) → POST /api/verify → EvidenceConsole.
 *
 * Holds the picked file locally (object URL for the preview; revoked on change/unmount — no leaks,
 * no persistence). Every state is designed: idle, drag-over, client-rejected, uploading/processing,
 * backend error, and the rendered verdict. No result is shown unless the backend returns one.
 */
export function UploadIntake() {
  const [selected, setSelected] = useState<SelectedFile | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [isDragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dragDepth = useRef(0);

  const verify = useVerifyDocument();

  // Revoke the previous object URL whenever the selection changes or the component unmounts.
  useEffect(() => {
    return () => {
      if (selected?.previewUrl) URL.revokeObjectURL(selected.previewUrl);
    };
  }, [selected]);

  const acceptFile = useCallback(
    (file: File) => {
      const reason = rejectReason(file);
      if (reason) {
        setClientError(reason);
        return;
      }
      setClientError(null);
      verify.reset();
      setSelected((prev) => {
        if (prev?.previewUrl) URL.revokeObjectURL(prev.previewUrl);
        const pdf = isPdf(file);
        const previewUrl = !pdf && isPreviewableImage(file) ? URL.createObjectURL(file) : null;
        return { file, previewUrl, isPdf: pdf };
      });
      verify.mutate({ file });
    },
    [verify],
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) acceptFile(file);
    e.target.value = ""; // allow re-selecting the same file
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) acceptFile(file);
  };

  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) setDragging(false);
  };

  const retry = () => {
    if (selected) verify.mutate({ file: selected.file });
  };

  const clearAndReset = () => {
    if (selected?.previewUrl) URL.revokeObjectURL(selected.previewUrl);
    setSelected(null);
    setClientError(null);
    verify.reset();
  };

  const dropError = clientError;

  return (
    <div className="space-y-5">
      {/* The dropzone — always present so re-uploads are one action away. */}
      <div
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        role="button"
        tabIndex={0}
        aria-label="Upload a document to verify. Drag and drop a PDF or image here, or press Enter to browse."
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          isDragging
            ? "border-accent bg-accent/5"
            : "border-hairline bg-surface/40 hover:border-accent/60 hover:bg-surface/70",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          onChange={onInputChange}
          className="sr-only"
          aria-hidden="true"
          tabIndex={-1}
        />
        <span
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full border text-xl transition-colors",
            isDragging ? "border-accent text-accent" : "border-hairline text-slate-400 group-hover:text-accent",
          )}
          aria-hidden="true"
        >
          ⤓
        </span>
        <div>
          <p className="text-sm font-semibold text-slate-100">
            {isDragging ? "Drop to verify" : "Drag a document here, or click to browse"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            PDF or image · up to {formatBytes(25 * 1024 * 1024)} · treated as hostile and verified server-side
          </p>
        </div>
        {selected && (
          <p className="text-xs text-slate-400">
            Selected: <span className="font-medium text-slate-200">{selected.file.name}</span>{" "}
            ({formatBytes(selected.file.size)})
          </p>
        )}
      </div>

      {/* Client-side rejection (too large / wrong type / empty). */}
      {dropError && (
        <StateMessage
          tone="error"
          title="That file can't be verified"
          detail={dropError}
          icon={<span className="text-2xl">⚠</span>}
        />
      )}

      {/* Processing. */}
      {verify.isPending && (
        <StateMessage
          tone="loading"
          title="Running the verification waterfall…"
          detail="Provenance → forensics → arithmetic consistency. The document is processed in memory and never persisted."
        />
      )}

      {/* Backend / network error — surfaced honestly, with retry. */}
      {verify.isError && !verify.isPending && (
        <StateMessage
          tone="error"
          title="Verification could not complete"
          detail={
            <>
              <p>{verify.error.message}</p>
              {verify.error instanceof ApiError && verify.error.status && (
                <p className="mt-1 font-mono text-xs text-slate-500">HTTP {verify.error.status}</p>
              )}
            </>
          }
          icon={<span className="text-2xl">⚠</span>}
          action={
            <div className="flex gap-2">
              <button
                type="button"
                onClick={retry}
                className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent/20"
              >
                Retry
              </button>
              <button
                type="button"
                onClick={clearAndReset}
                className="rounded-md border border-hairline px-3 py-1.5 text-sm text-slate-300 hover:bg-surface-2"
              >
                Choose another file
              </button>
            </div>
          }
        />
      )}

      {/* The verdict. */}
      {verify.isSuccess && selected && (
        <EvidenceConsole
          trust={verify.data}
          previewUrl={selected.previewUrl}
          isPdf={selected.isPdf}
          fileName={selected.file.name}
        />
      )}
    </div>
  );
}
