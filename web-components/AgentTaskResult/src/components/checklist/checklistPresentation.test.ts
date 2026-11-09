import { describe, expect, it } from 'vitest';
import {
  checklistActorLabel,
  checklistCounterLabel,
  checklistCounterText,
  checklistEventSummary,
  checklistItemAriaLabel,
  checklistPillTone,
  prioritizeChecklistItems,
  safeChecklistRefUrl,
} from './checklistPresentation';
import { makeChecklistItem } from './checklistTestData';

const counts = (overrides: Partial<{ done: number; total: number; waitingUser: number; closed: boolean }> = {}) => ({ done: 2, total: 5, waitingUser: 0, closed: false, ...overrides });

describe('checklist presentation', () => {
  it('reads the counter as done over total', () => {
    expect(checklistCounterText(counts())).toBe('2/5');
    expect(checklistCounterLabel(counts())).toBe('Checklist, 2 of 5 done');
    expect(checklistCounterLabel(counts({ waitingUser: 2 }))).toBe('Checklist, 2 of 5 done, 2 need your input');
    expect(checklistCounterLabel(counts({ closed: true }))).toBe('Checklist, 2 of 5 done, tracking stopped');
  });

  it('picks the amber tone for a wait on the reader, the complete tone when all done, and neutral otherwise', () => {
    expect(checklistPillTone(counts({ waitingUser: 1 }))).toBe('attention');
    expect(checklistPillTone(counts({ done: 5 }))).toBe('complete');
    expect(checklistPillTone(counts({ done: 0, total: 0 }))).toBe('neutral');
    expect(checklistPillTone(counts())).toBe('neutral');
  });

  it('orders open items by what the reader needs first, then done, then dropped, and leaves archived out', () => {
    const items = [
      makeChecklistItem({ id: 'dropped', status: 'dropped' }),
      makeChecklistItem({ id: 'done', status: 'done' }),
      makeChecklistItem({ id: 'external', status: 'waiting_external' }),
      makeChecklistItem({ id: 'pending', status: 'pending', sort_order: 5 }),
      makeChecklistItem({ id: 'pending-first', status: 'pending', sort_order: 1 }),
      makeChecklistItem({ id: 'progress', status: 'in_progress' }),
      makeChecklistItem({ id: 'you', status: 'waiting_user' }),
      makeChecklistItem({ id: 'archived', status: 'waiting_user', archived_at: '2026-11-03 10:00:00' }),
    ];

    expect(prioritizeChecklistItems(items).map(item => item.id)).toEqual(['you', 'progress', 'pending-first', 'pending', 'external', 'done', 'dropped']);
  });

  it('describes an item for a screen reader with its state, what it waits on, and whether it is required', () => {
    const item = makeChecklistItem({ title: 'Choose a time', status: 'waiting_user', waiting_on: 'Your calendar', required: true });
    expect(checklistItemAriaLabel(item)).toBe('Choose a time, needs your input: Your calendar, required');
    expect(checklistItemAriaLabel(makeChecklistItem({ title: 'Plain', status: 'pending', waiting_on: 'stale text' }))).toBe('Plain, to do');
  });

  it('turns logged status names into the labels the reader sees', () => {
    expect(checklistEventSummary('status', 'pending to waiting_user: needs a time')).toBe('Changed status: to do to needs your input: needs a time');
    expect(checklistEventSummary('added', 'Book a GP visit')).toBe('Added: Book a GP visit');
    expect(checklistEventSummary('unheard_of_kind', '')).toBe('unheard of kind');
  });

  it('names who acted', () => {
    expect(checklistActorLabel('user')).toBe('You');
    expect(checklistActorLabel('agent')).toBe('Basil');
    expect(checklistActorLabel('system')).toBe('system');
  });

  it('links only http and https references', () => {
    const ref = (open_url: string | null) => ({ id: 'r', item_id: 'i', role: 'primary', ref_kind: 'k', source_system: 's', source_scope: '', external_id: 'e', label: 'l', open_url, added_by: null, last_known_status: null, last_known_at: null });
    expect(safeChecklistRefUrl(ref('https://example.com/a?b=1'))).toBe('https://example.com/a?b=1');
    expect(safeChecklistRefUrl(ref('http://example.com'))).toBe('http://example.com/');
    expect(safeChecklistRefUrl(ref('javascript:alert(1)'))).toBeNull();
    expect(safeChecklistRefUrl(ref('file:///etc/passwd'))).toBeNull();
    expect(safeChecklistRefUrl(ref('not a url'))).toBeNull();
    expect(safeChecklistRefUrl(ref(null))).toBeNull();
  });
});
