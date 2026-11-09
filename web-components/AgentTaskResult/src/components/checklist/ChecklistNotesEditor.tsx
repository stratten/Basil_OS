import { useEffect, useRef, useState } from 'react';
import * as checklistApi from '../../services/checklistApi';
import type { ChecklistNotes } from '../../services/checklistApi';
import type { ChecklistActions } from '../../store/checklistStore';

interface Props {
  notes: ChecklistNotes;
  maxChars: number;
  actions: ChecklistActions;
}

function notesLabel(notes: ChecklistNotes): string {
  if (notes.carried_from_task_id && notes.updated_by === 'system') return 'Carried from the previous run. Basil verifies these before relying on them.';
  if (notes.revision === 0) return 'Nothing noted yet.';
  return notes.updated_by === 'user' ? 'Last edited by you.' : 'Last edited by Basil.';
}

/**
 * The chain's working notes: one short document describing where things stand now, never a history. Basil reads it every turn, so the cap is a hard limit. An edit from the other side while this is open is not overwritten: the reader's text stays and saving it again is a deliberate act.
 */
export default function ChecklistNotesEditor({ notes, maxChars, actions }: Props) {
  const [text, setText] = useState(notes.content);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const savedContent = useRef(notes.content);

  useEffect(() => {
    const previous = savedContent.current;
    savedContent.current = notes.content;
    setText(current => (current === previous ? notes.content : current));
  }, [notes.content, notes.revision]);

  const dirty = text !== notes.content;
  const remaining = maxChars - text.length;
  const overLimit = remaining < 0;

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await actions.saveNotes(text, notes.revision);
    } catch (error) {
      if (checklistApi.isChecklistConflict(error)) {
        setMessage('Basil changed the notes while you were editing. The latest notes are loaded and your text is kept here. Save again to replace them.');
      } else {
        setMessage(error instanceof Error ? error.message : 'The notes could not be saved.');
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="checklist-notes">
      <p className="checklist-notes__status">{notesLabel(notes)}</p>
      <label className="checklist-field__label" htmlFor="checklist-notes-text">Working notes</label>
      <textarea
        id="checklist-notes-text"
        className="checklist-field__input checklist-field__input--notes"
        value={text}
        rows={10}
        onChange={event => setText(event.target.value)}
        aria-describedby="checklist-notes-count"
      />
      <div className="checklist-notes__footer">
        <span id="checklist-notes-count" className={`checklist-notes__count${overLimit ? ' is-over' : ''}`}>
          {overLimit ? `${-remaining} characters over the ${maxChars} limit. Condense the notes to save.` : `${remaining} characters left`}
        </span>
        <button type="button" className="checklist-button checklist-button--primary" disabled={!dirty || saving || overLimit} onClick={() => void save()}>
          {saving ? 'Saving...' : 'Save notes'}
        </button>
      </div>
      {message && <p className="checklist-notes__message" role="alert">{message}</p>}
    </div>
  );
}
