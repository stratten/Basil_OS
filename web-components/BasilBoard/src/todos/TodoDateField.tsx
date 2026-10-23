import { useEffect, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import useAutosaveField, { type AutosaveStatus } from './useAutosaveField';

const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/**
 * An empty value clears the date. A native date input reports a value for every year digit typed ("0002", "0020",
 * "0202", "2026"), so a year before 1000 is a partial entry that must never be sent to the server.
 */
export function isCommittableDateValue(value: string): boolean {
  return value === '' || (DATE_ONLY_PATTERN.test(value) && Number(value.slice(0, 4)) >= 1000);
}

interface TodoDateFieldProps {
  itemId: string;
  /** The persisted calendar day as YYYY-MM-DD, or an empty string when no date is set. */
  serverValue: string;
  /** Text shown while not editing for the persisted date, or null when no date is set. */
  serverDisplay: string | null;
  /** Formats an unsaved YYYY-MM-DD draft for display while it is being saved or after a failed save. */
  formatDraft: (dateOnly: string) => string;
  emptyLabel: string;
  inputLabel: string;
  controlsClassName: string;
  /** Extra content shown next to the date while not editing, such as an overdue badge. */
  trailing?: ReactNode;
  /** Persists a YYYY-MM-DD day, or an empty string to clear it. Resolves true when the server accepted it. */
  onSave: (dateOnly: string) => Promise<boolean>;
  onStatusChange: (status: AutosaveStatus) => void;
}

/**
 * Click-to-edit date. The date is saved when the input loses focus or Enter is pressed, never while the user is
 * still choosing segments, and Escape or Cancel discards the edit.
 */
export default function TodoDateField({
  itemId, serverValue, serverDisplay, formatDraft, emptyLabel, inputLabel, controlsClassName, trailing, onSave, onStatusChange,
}: TodoDateFieldProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [clearing, setClearing] = useState(false);
  const field = useAutosaveField({
    itemId,
    serverValue,
    isValid: isCommittableDateValue,
    save: onSave,
  });

  useEffect(() => {
    setIsEditing(false);
  }, [itemId]);

  useEffect(() => {
    onStatusChange(field.status);
  }, [field.status, onStatusChange]);

  // The input can be unmounted while still focused, so the hook is told explicitly that focus has left.
  function closeEditor(): void {
    field.onBlur();
    setIsEditing(false);
  }

  function discardAndClose(): void {
    field.revert();
    closeEditor();
  }

  async function clearDate(): Promise<void> {
    field.revert();
    setClearing(true);
    try {
      await onSave('');
    } finally {
      setClearing(false);
      closeEditor();
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      event.currentTarget.blur();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      discardAndClose();
    }
  }

  // Keeping focus on the input while a button is pressed stops the blur from saving a half-finished edit first.
  const keepInputFocus = (event: MouseEvent<HTMLButtonElement>) => event.preventDefault();

  if (isEditing) {
    return (
      <div className={controlsClassName}>
        <input
          type="date"
          value={field.draft}
          aria-label={inputLabel}
          autoFocus
          onChange={(event) => field.setDraft(event.target.value)}
          onFocus={field.onFocus}
          onBlur={closeEditor}
          onKeyDown={handleKeyDown}
        />
        {serverValue && (
          <button type="button" className="todo-detail-due-clear" disabled={clearing} onMouseDown={keepInputFocus} onClick={() => void clearDate()}>
            Clear
          </button>
        )}
        <button type="button" className="todo-detail-date-edit-cancel" disabled={clearing} onMouseDown={keepInputFocus} onClick={discardAndClose}>
          Cancel
        </button>
      </div>
    );
  }

  const unsavedDraftShown = field.status === 'saving' || field.status === 'error';
  const shown = unsavedDraftShown ? (field.draft ? formatDraft(field.draft) : null) : serverDisplay;
  return (
    <div className="todo-detail-date-display">
      <button type="button" className="todo-detail-date-display-value" onClick={() => setIsEditing(true)}>
        {shown ?? emptyLabel}
      </button>
      {trailing}
    </div>
  );
}
