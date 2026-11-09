import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChecklistItem } from '../../services/checklistApi';

export type ChecklistDraftField = 'title' | 'detail' | 'waiting_on' | 'note';

export type ChecklistDraft = Record<ChecklistDraftField, string>;

const FIELDS: readonly ChecklistDraftField[] = ['title', 'detail', 'waiting_on', 'note'];

function fromItem(item: ChecklistItem): ChecklistDraft {
  return { title: item.title, detail: item.detail, waiting_on: item.waiting_on, note: item.note };
}

/**
 * Text fields the reader is typing into, kept apart from the stored item. When the stored item changes under them (the agent updated it), a field the reader has not touched takes the new value and a field with unsaved typing keeps it, so an update never overwrites what is being typed.
 */
export function useChecklistItemDraft(item: ChecklistItem) {
  const [draft, setDraft] = useState<ChecklistDraft>(() => fromItem(item));
  const base = useRef<ChecklistDraft>(fromItem(item));

  useEffect(() => {
    const next = fromItem(item);
    const previous = base.current;
    base.current = next;
    setDraft(current => {
      const merged = { ...current };
      for (const field of FIELDS) {
        if (current[field] === previous[field]) merged[field] = next[field];
      }
      return merged;
    });
  }, [item.revision, item.title, item.detail, item.waiting_on, item.note]);

  const setField = useCallback((field: ChecklistDraftField, value: string) => {
    setDraft(current => ({ ...current, [field]: value }));
  }, []);

  /** The fields that differ from what is stored, ready to send. A blank title is not a change: it is restored. */
  const dirtyChanges = useCallback((): Partial<ChecklistDraft> => {
    const changes: Partial<ChecklistDraft> = {};
    for (const field of FIELDS) {
      if (draft[field] === base.current[field]) continue;
      if (field === 'title' && draft.title.trim() === '') continue;
      changes[field] = draft[field];
    }
    return changes;
  }, [draft]);

  const restoreBlankTitle = useCallback(() => {
    setDraft(current => (current.title.trim() === '' ? { ...current, title: base.current.title } : current));
  }, []);

  return { draft, setField, dirtyChanges, restoreBlankTitle };
}
