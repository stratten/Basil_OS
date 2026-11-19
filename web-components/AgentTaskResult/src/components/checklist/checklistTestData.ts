import type { ChecklistCounts, ChecklistItem, ChecklistSnapshot } from '../../services/checklistApi';

export function makeChecklistItem(overrides: Partial<ChecklistItem> = {}): ChecklistItem {
  return {
    id: 'item-1',
    origin: 'agent',
    title: 'Book a GP visit',
    detail: '',
    status: 'pending',
    done_basis: '',
    required: false,
    note: '',
    waiting_on: '',
    recheck_at: null,
    sort_order: 0,
    work_item_id: null,
    carried_from_item_id: null,
    archived_at: null,
    revision: 1,
    created_by_task_id: 'root-1',
    updated_by_task_id: null,
    created_at: '2026-11-03 09:00:00',
    updated_at: '2026-11-03 09:00:00',
    refs: [],
    ...overrides,
  };
}

export function countsFor(items: readonly ChecklistItem[]): ChecklistCounts {
  const counted = items.filter(item => !item.archived_at && item.status !== 'dropped');
  return {
    total: counted.length,
    done: counted.filter(item => item.status === 'done').length,
    open: counted.filter(item => item.status !== 'done').length,
    waiting_user: counted.filter(item => item.status === 'waiting_user').length,
    waiting_external: counted.filter(item => item.status === 'waiting_external').length,
    required_open: counted.filter(item => item.required && item.status !== 'done').length,
  };
}

export function makeChecklistSnapshot(items: ChecklistItem[] = [], overrides: Partial<ChecklistSnapshot> = {}): ChecklistSnapshot {
  return {
    root_task_id: 'root-1',
    exists: items.length > 0,
    closed_at: null,
    items,
    counts: countsFor(items),
    notes: { content: '', revision: 0, updated_by: null, updated_at: null, carried_from_task_id: null },
    notes_max_chars: 4000,
    ...overrides,
  };
}
