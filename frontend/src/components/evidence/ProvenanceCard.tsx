import { ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Provenance } from "@/api/types";
import { Panel } from "@/components/primitives/Panel";
import { Tag } from "@/components/primitives/Tag";
import { cn } from "@/lib/cn";

interface ProvenanceCardProps {
  provenance: Provenance;
  tierLabel: string;
}

type ProvState = "verified" | "tampered" | "none";

function provState(p: Provenance): ProvState {
  if (p.tampered) return "tampered";
  if (p.verified) return "verified";
  return "none";
}

const STATE_COPY: Record<
  ProvState,
  { title: string; tone: string; ring: string; sub: string; Icon: LucideIcon }
> = {
  verified: {
    title: "Source verified",
    tone: "text-verdict-approved",
    ring: "border-verdict-approved/50 bg-verdict-approved-soft",
    sub: "Cryptographic signature chains to a pinned trust anchor.",
    Icon: ShieldCheck,
  },
  tampered: {
    title: "Signature invalid — tampering",
    tone: "text-verdict-rejected",
    ring: "border-verdict-rejected/50 bg-verdict-rejected-soft",
    sub: "A signature is present but failed validation — active tampering evidence.",
    Icon: ShieldX,
  },
  none: {
    title: "No verifiable source",
    tone: "text-verdict-pending",
    ring: "border-verdict-pending/40 bg-verdict-pending-soft",
    sub: "No cryptographic source of truth — fell back to forensic analysis.",
    Icon: ShieldQuestion,
  },
};

/**
 * Tier-1 provenance result: verified / tampered / none, with the verification METHOD (PAdES, C2PA,
 * DigiLocker, AA…) and the tier the waterfall reached. All values come from TrustScore.provenance.
 */
export function ProvenanceCard({ provenance, tierLabel }: ProvenanceCardProps) {
  const state = provState(provenance);
  const copy = STATE_COPY[state];

  return (
    <Panel title="Provenance" icon={ShieldCheck} aside={<Tag tone="accent">{tierLabel}</Tag>}>
      <div className={cn("flex items-start gap-3 rounded-lg border px-4 py-3", copy.ring)}>
        <copy.Icon size={22} className={cn("mt-0.5 shrink-0", copy.tone)} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <p className={cn("text-sm font-semibold", copy.tone)}>{copy.title}</p>
            <Tag title="Verification method reported by Tier-1">
              {provenance.method || "none"}
            </Tag>
          </div>
          <p className="mt-1 text-sm text-slate-400">{copy.sub}</p>
          {provenance.detail && (
            <p className="mt-2 rounded bg-black/25 px-2 py-1 font-mono text-xs text-slate-300">
              {provenance.detail}
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}
