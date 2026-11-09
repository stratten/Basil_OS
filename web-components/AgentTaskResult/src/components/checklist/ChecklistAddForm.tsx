import { useState, type FormEvent, type KeyboardEvent } from 'react';
import type { ChecklistActions } from '../../store/checklistStore';
import { CHECKLIST_TITLE_MAX_CHARS } from './checklistPresentation';

interface Props {
  actions: ChecklistActions;
}

/** Adds an item as the reader. Basil sees it on its next turn and treats it like any other item. */
export default function ChecklistAddForm({ actions }: Props) {
  const [title, setTitle] = useState('');
  const [required, setRequired] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = title.trim();

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!trimmed || saving) return;
    setSaving(true);
    setError(null);
    try {
      await actions.addItem({ title: trimmed, required });
      setTitle('');
      setRequired(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The item could not be added.');
    } finally {
      setSaving(false);
    }
  }

  function submitOnCommandReturn(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form className="checklist-add" onSubmit={event => void submit(event)}>
      <textarea
        className="checklist-field__input checklist-add__input"
        value={title}
        rows={3}
        maxLength={CHECKLIST_TITLE_MAX_CHARS}
        placeholder="Describe something that still needs to happen"
        aria-label="New checklist item"
        onChange={event => setTitle(event.target.value)}
        onKeyDown={submitOnCommandReturn}
      />
      <div className="checklist-add__row">
        <label className="checklist-detail__required">
          <input type="checkbox" checked={required} onChange={event => setRequired(event.target.checked)} />
          <span>Required before the run is finished</span>
        </label>
        <button type="submit" className="checklist-button checklist-button--primary" disabled={!trimmed || saving} title="Add the step (Command-Return)">
          {saving ? 'Adding...' : 'Add'}
        </button>
      </div>
      {error && <p className="checklist-add__error" role="alert">{error}</p>}
    </form>
  );
}
