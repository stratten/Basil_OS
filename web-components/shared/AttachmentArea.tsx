import { useId } from 'react';
import './attachment-area.css';
import AttachmentDropZone from './AttachmentDropZone';
import AttachmentList from './AttachmentList';
import { PaperclipGlyph } from './attachmentGlyphs';
import { ATTACHMENTS_LABEL, ATTACH_BUTTON_LABEL, EMPTY_ATTACHMENTS_TEXT, READ_ONLY_EMPTY_TEXT, type AttachmentEntry } from './attachmentPaths';

export interface AttachmentAreaProps {
  entries: readonly AttachmentEntry[];
  /** False draws a read-only list: no Add button, no remove buttons, no drop highlight. */
  canEdit: boolean;
  /** True while a save is in flight: the button, the removes and the drop zone are disabled. */
  busy?: boolean;
  error?: string | null;
  onPick: () => void;
  onRemove?: (entry: AttachmentEntry, index: number) => void;
  onOpen?: (entry: AttachmentEntry) => void;
  onReveal?: (entry: AttachmentEntry) => void;
  onArm?: () => void;
  onDisarm?: () => void;
  /** Forwarded to the drop zone. Default true; Companion passes false (see AttachmentDropZone). */
  disarmOnDrop?: boolean;
  emptyText?: string;
  readOnlyEmptyText?: string;
  /** Extra class on the heading so a host keeps its own heading typography. */
  titleClassName?: string;
  className?: string;
  zoneTestId?: string;
}

/** A standalone attachments section: heading, Add button, a drop zone sized to the section, the chip list and an inline error. */
export default function AttachmentArea({
  entries,
  canEdit,
  busy = false,
  error = null,
  onPick,
  onRemove,
  onOpen,
  onReveal,
  onArm,
  onDisarm,
  disarmOnDrop = true,
  emptyText = EMPTY_ATTACHMENTS_TEXT,
  readOnlyEmptyText = READ_ONLY_EMPTY_TEXT,
  titleClassName,
  className,
  zoneTestId,
}: AttachmentAreaProps) {
  const errorId = useId();
  const zoneProps = zoneTestId ? { 'data-testid': zoneTestId } : {};
  return (
    <section className={className ? `attachment-area ${className}` : 'attachment-area'} aria-label={ATTACHMENTS_LABEL}>
      <div className="attachment-area__heading">
        <h3 className={titleClassName ? `attachment-area__title ${titleClassName}` : 'attachment-area__title'}>
          <PaperclipGlyph size={11} />
          <span>{ATTACHMENTS_LABEL}</span>
        </h3>
        {canEdit && (
          <button type="button" className="attachment-area__add" disabled={busy} onClick={onPick} title={ATTACH_BUTTON_LABEL} aria-label={ATTACH_BUTTON_LABEL}>
            <PaperclipGlyph size={11} />
            <span>Add…</span>
          </button>
        )}
      </div>
      <AttachmentDropZone {...zoneProps} className="attachment-area__zone" disabled={!canEdit || busy} onArm={canEdit ? onArm : undefined} onDisarm={onDisarm} disarmOnDrop={disarmOnDrop} aria-describedby={error ? errorId : undefined}>
        {entries.length === 0 ? (
          <p className="attachment-area__empty">{canEdit ? emptyText : readOnlyEmptyText}</p>
        ) : (
          <AttachmentList
            className="attachment-list--area"
            entries={entries}
            showHeading={false}
            onRemove={canEdit ? onRemove : undefined}
            removeDisabled={busy}
            onOpen={onOpen}
            onReveal={onReveal}
          />
        )}
      </AttachmentDropZone>
      {error && <p id={errorId} className="attachment-area__error" role="alert">{error}</p>}
    </section>
  );
}
