import type { MouseEvent } from 'react';
import './inline-delete-confirm.css';

export interface InlineDeleteConfirmProps {
  label: string;
  onCancel: () => void;
  onConfirm: () => void;
  busy?: boolean;
  busyLabel?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  layout?: 'inline' | 'stacked';
  ariaLabel?: string;
  className?: string;
}

/** The in-place "Delete this thing?" row: a label with Cancel and a danger Delete, themed only through tokens. Click propagation is stopped so a confirmation inside a selectable row never also selects the row. */
export function InlineDeleteConfirm({
  label,
  onCancel,
  onConfirm,
  busy = false,
  busyLabel = 'Deleting...',
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  layout = 'inline',
  ariaLabel,
  className,
}: InlineDeleteConfirmProps) {
  const rootClassName = [
    'inline-delete-confirm',
    layout === 'stacked' ? 'inline-delete-confirm--stacked' : '',
    className ?? '',
  ].filter(Boolean).join(' ');

  const handleCancel = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onCancel();
  };

  const handleConfirm = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onConfirm();
  };

  return (
    <div className={rootClassName} role={ariaLabel ? 'alertdialog' : undefined} aria-label={ariaLabel}>
      <span className="inline-delete-confirm__label">{label}</span>
      <div className="inline-delete-confirm__actions">
        <button type="button" className="inline-delete-confirm__btn" onClick={handleCancel}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className="inline-delete-confirm__btn inline-delete-confirm__btn--danger"
          onClick={handleConfirm}
          disabled={busy}
        >
          {busy ? busyLabel : confirmLabel}
        </button>
      </div>
    </div>
  );
}
