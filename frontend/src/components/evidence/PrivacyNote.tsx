import { ShieldCheck } from "lucide-react";

interface PrivacyNoteProps {
  note: string;
}

/**
 * The privacy note (CLAUDE.md §10: ephemeral processing, no document/frame persistence). Rendered
 * verbatim from evidence_pack.privacy_note so the UI's privacy claim matches the backend's actual
 * behaviour rather than restating it independently.
 */
export function PrivacyNote({ note }: PrivacyNoteProps) {
  return (
    <p className="flex items-start gap-2 text-xs text-text-tertiary sm:max-w-md sm:text-right">
      <ShieldCheck size={14} className="mt-px shrink-0 text-accent/80 sm:order-last" aria-hidden="true" />
      <span>{note}</span>
    </p>
  );
}
