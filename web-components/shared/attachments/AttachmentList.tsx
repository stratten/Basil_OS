import './attachment-area.css';
import { ConnectionGlyph, DocGlyph, FolderGlyph, PaperclipGlyph, RevealGlyph } from './attachmentGlyphs';
import { ATTACHMENTS_LABEL, attachmentBasename, attachmentIsDirectory, type AttachmentEntry } from './attachmentPaths';

export interface AttachmentListProps {
  entries: readonly AttachmentEntry[];
  /** Omit for a read-only list. */
  onRemove?: (entry: AttachmentEntry, index: number) => void;
  removeDisabled?: boolean;
  /** When supplied the name is a button that opens the item. */
  onOpen?: (entry: AttachmentEntry) => void;
  /** When supplied a Reveal in Finder button follows the name. */
  onReveal?: (entry: AttachmentEntry) => void;
  /** The small paperclip heading inside the list; hosts that draw their own heading pass false. */
  showHeading?: boolean;
  /** Modifier classes such as `attachment-list--inset`, `attachment-list--flush` or `attachment-list--area`. */
  className?: string;
  /** The accessible name of the group; defaults to "Attachments". A host listing something other than attachments names it. */
  groupLabel?: string;
}

/** The one attachment chip list: icon, name, optional open and reveal, optional remove. Renders nothing when empty. */
export default function AttachmentList({ entries, onRemove, removeDisabled = false, onOpen, onReveal, showHeading = true, className, groupLabel = ATTACHMENTS_LABEL }: AttachmentListProps) {
  if (entries.length === 0) return null;
  return (
    <div className={className ? `attachment-list ${className}` : 'attachment-list'} role="group" aria-label={groupLabel}>
      {showHeading && (
        <div className="attachment-list__header">
          <PaperclipGlyph />
          <span>{ATTACHMENTS_LABEL}</span>
        </div>
      )}
      <div className="attachment-list__rows">
        {entries.map((entry, index) => {
          const name = entry.name ?? attachmentBasename(entry.path);
          const tooltip = entry.title ?? entry.path;
          const isConnection = entry.kind === 'connection';
          return (
            <div key={entry.key} className={entry.pending ? 'attachment-list__row is-pending' : 'attachment-list__row'} data-attachment-kind={isConnection ? 'connection' : undefined}>
              <span className="attachment-list__row-icon" aria-hidden="true">
                {isConnection ? <ConnectionGlyph /> : attachmentIsDirectory(entry) ? <FolderGlyph /> : <DocGlyph />}
              </span>
              {onOpen && !isConnection ? (
                <button
                  type="button"
                  className="attachment-list__row-name is-link"
                  title={tooltip}
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpen(entry);
                  }}
                >
                  {name}
                </button>
              ) : (
                <span className="attachment-list__row-name" title={tooltip}>{name}</span>
              )}
              {onReveal && !isConnection && (
                <button
                  type="button"
                  className="attachment-list__row-reveal"
                  title="Reveal in Finder"
                  aria-label={`Reveal ${name} in Finder`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onReveal(entry);
                  }}
                >
                  <RevealGlyph />
                </button>
              )}
              {onRemove && (
                <button
                  type="button"
                  className="attachment-list__row-remove"
                  disabled={removeDisabled}
                  title={entry.removeLabel ?? `Remove ${name}`}
                  aria-label={entry.removeLabel ?? `Remove ${name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemove(entry, index);
                  }}
                >
                  ✕
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
