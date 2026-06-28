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
    <p className="flex items-start gap-2 rounded-lg border border-hairline bg-surface/50 px-3 py-2 text-xs text-slate-400">
      <span aria-hidden="true" className="mt-px text-accent">
        ⛨
      </span>
      <span>{note}</span>
    </p>
  );
}
