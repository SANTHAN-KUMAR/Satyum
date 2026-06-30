import type { TrustScore } from "@/api/types";
import { Tag } from "@/components/primitives/Tag";
import { MODE_LABEL } from "@/lib/verdict";

interface CaseMetaProps {
  trust: TrustScore;
}

/** Compact case-identity strip: session id, intake mode, declared document type. */
export function CaseMeta({ trust }: CaseMetaProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
      <Tag title="Verification session identifier (correlation id)">
        session <span className="font-mono text-text-secondary">{trust.session_id}</span>
      </Tag>
      <Tag tone="accent" title="Capture medium for this case">
        intake: {MODE_LABEL[trust.intake_mode] ?? trust.intake_mode}
      </Tag>
      <Tag title="Document type">doc: {trust.doc_type ?? "unclassified"}</Tag>
    </div>
  );
}
