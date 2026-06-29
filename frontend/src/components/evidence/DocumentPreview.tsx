import { FileText, ScanSearch } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { TamperEvidenceRegion } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { Tag } from "@/components/primitives/Tag";
import { cn } from "@/lib/cn";

interface DocumentPreviewProps {
  /** Object URL of the locally-held intake (image). PDFs render an honest non-image placeholder. */
  previewUrl: string | null;
  isPdf: boolean;
  fileName: string;
  regions: TamperEvidenceRegion[];
}

/**
 * The document preview with the tamper-evidence region overlay (CLAUDE.md §9 "the deterministic
 * tamper-evidence map ... only regions traced to a real detector").
 *
 * Bboxes are in the ANALYSED-image pixel space (EvidenceRegion.bbox = x, y, w, h). The backend does
 * NOT return the analysed-image dimensions on the evidence pack, so we scale relative to the
 * displayed preview's natural pixel size — correct when the analysed image is the same page we hold
 * locally (the file path). Each region is labelled with its producing detector (region.source) for
 * auditability; we never invent a region.
 */
export function DocumentPreview({ previewUrl, isPdf, fileName, regions }: DocumentPreviewProps) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const titleId = useId();

  // Reset natural dims when the source changes.
  useEffect(() => {
    setNatural(null);
  }, [previewUrl]);

  const hasOverlay = regions.length > 0;

  return (
    <Panel
      title="Document preview"
      aside={
        hasOverlay ? (
          <Tag tone="warn">{regions.length} flagged region{regions.length === 1 ? "" : "s"}</Tag>
        ) : (
          <Tag>no flagged regions</Tag>
        )
      }
    >
      <figure className="space-y-2" aria-labelledby={titleId}>
        <div className="relative overflow-hidden rounded-lg border border-hairline bg-black/40">
          {isPdf || !previewUrl ? (
            <div className="flex min-h-[280px] flex-col items-center justify-center gap-2 p-6 text-center">
              <FileText size={40} strokeWidth={1.5} className="text-slate-500" aria-hidden="true" />
              <p className="text-sm font-medium text-slate-300">{fileName}</p>
              <p className="max-w-xs text-xs text-slate-500">
                {isPdf
                  ? "PDF intake — page rendering is handled server-side; the flagged regions below reference the analysed page."
                  : "No inline preview available for this intake."}
              </p>
              {hasOverlay && (
                <ul className="mt-2 w-full space-y-1 text-left">
                  {regions.map((r, i) => (
                    <li
                      key={`${r.source}-${i}`}
                      className="flex items-start gap-2 rounded border border-verdict-rejected/40 bg-verdict-rejected-soft px-2 py-1.5 text-xs text-slate-300"
                    >
                      <ScanSearch
                        size={13}
                        className="mt-0.5 shrink-0 text-verdict-rejected"
                        aria-hidden="true"
                      />
                      <span>
                        <span className="font-medium text-slate-200">{r.label}</span>
                        <span className="text-slate-500"> · detector: {r.source}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <>
              <img
                ref={imgRef}
                src={previewUrl}
                alt={`Uploaded document: ${fileName}`}
                className="block h-auto w-full"
                onLoad={(e) =>
                  setNatural({
                    w: e.currentTarget.naturalWidth,
                    h: e.currentTarget.naturalHeight,
                  })
                }
              />
              {natural && hasOverlay && (
                <svg
                  className="pointer-events-none absolute inset-0 h-full w-full"
                  viewBox={`0 0 ${natural.w} ${natural.h}`}
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  {regions.map((r, i) => {
                    const [x, y, w, h] = r.bbox;
                    return (
                      <g key={`${r.source}-${i}`}>
                        <rect
                          x={x}
                          y={y}
                          width={w}
                          height={h}
                          fill="#dc262622"
                          stroke="#dc2626"
                          strokeWidth={Math.max(2, natural.w * 0.003)}
                        />
                        <rect
                          x={x}
                          y={Math.max(0, y - natural.h * 0.028)}
                          width={Math.min(w, natural.w * 0.45)}
                          height={natural.h * 0.026}
                          fill="#dc2626"
                        />
                        <text
                          x={x + 4}
                          y={Math.max(natural.h * 0.02, y - natural.h * 0.008)}
                          fill="#fff"
                          fontSize={natural.h * 0.018}
                          fontFamily="ui-monospace, monospace"
                        >
                          {r.source}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </>
          )}
        </div>

        {/* Accessible textual list of the regions (the overlay itself is aria-hidden). */}
        {!isPdf && previewUrl && hasOverlay && (
          <figcaption id={titleId} className="space-y-1">
            <p className="sr-only">Tamper-evidence regions overlaid on the document:</p>
            <ul className="space-y-1">
              {regions.map((r, i) => (
                <li
                  key={`cap-${r.source}-${i}`}
                  className={cn(
                    "flex items-start gap-2 rounded border px-2 py-1 text-xs",
                    "border-verdict-rejected/30 bg-verdict-rejected-soft text-slate-300",
                  )}
                >
                  <ScanSearch
                    size={13}
                    className="mt-0.5 shrink-0 text-verdict-rejected"
                    aria-hidden="true"
                  />
                  <span>
                    <span className="font-medium text-slate-200">{r.label}</span>
                    <span className="text-slate-500">
                      {" "}
                      — detector: {r.source}
                      {r.suspicion != null && ` · suspicion ${r.suspicion.toFixed(2)}`}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </figcaption>
        )}
      </figure>
    </Panel>
  );
}
