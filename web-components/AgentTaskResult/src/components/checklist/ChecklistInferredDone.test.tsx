// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../../types';
import { checklistItemAriaLabel, isInferredDone } from './checklistPresentation';
import { makeChecklistItem, makeChecklistSnapshot } from './checklistTestData';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const api = vi.hoisted(() => ({
  getChecklist: vi.fn(),
  getChecklistItemLog: vi.fn(),
  addChecklistItem: vi.fn(),
  updateChecklistItem: vi.fn(),
  archiveChecklistItem: vi.fn(),
  closeChecklist: vi.fn(),
  saveChecklistNotes: vi.fn(),
  offerChecklistItemAsTodo: vi.fn(),
}));
vi.mock('../../services/api', () => ({ isApiReady: () => true }));
vi.mock('../../services/checklistApi', () => ({
  ...api,
  isChecklistConflict: (error: unknown) => error instanceof Error && /\(409\)$/.test(error.message),
}));
vi.mock('../../services/websocket', () => ({
  wsManager: { subscribe: () => () => {}, onConnect: () => () => {} } satisfies { subscribe: (handler: (event: WSEvent) => void) => () => void; onConnect: (handler: () => void) => () => void },
}));

import ChecklistWindow from './ChecklistWindow';
import { resetChecklistStoreForTests } from '../../store/checklistStore';
import { openChecklistWindow, resetChecklistViewForTests } from '../../store/checklistViewStore';

describe('isInferredDone', () => {
  it('is true only for a done item whose basis is inferred', () => {
    expect(isInferredDone(makeChecklistItem({ status: 'done', done_basis: 'inferred' }))).toBe(true);
    expect(isInferredDone(makeChecklistItem({ status: 'done', done_basis: '' }))).toBe(false);
    expect(isInferredDone(makeChecklistItem({ status: 'pending', done_basis: 'inferred' }))).toBe(false);
    expect(isInferredDone({ status: 'done' } as never)).toBe(false);
  });

  it('is announced to a screen reader and left out of an ordinary label', () => {
    expect(checklistItemAriaLabel(makeChecklistItem({ title: 'Archive it', status: 'done', done_basis: 'inferred' }))).toBe('Archive it, done, marked done by Basil from what it could see');
    expect(checklistItemAriaLabel(makeChecklistItem({ title: 'Archive it', status: 'done' }))).toBe('Archive it, done');
  });
});

describe('inferred done in the checklist window', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    resetChecklistStoreForTests();
    resetChecklistViewForTests();
    Object.values(api).forEach(mock => mock.mockReset());
    api.getChecklistItemLog.mockResolvedValue({ item_id: 'item-1', events: [], captured: [] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const click = async (element: Element) => {
    await act(async () => { (element as HTMLElement).click(); });
  };
  const detailButton = (label: string) => Array.from(container.querySelectorAll('.checklist-detail__actions button')).find(node => node.textContent === label) as HTMLButtonElement | undefined;
  const rowTags = () => Array.from(container.querySelectorAll('.checklist-row__tag')).map(node => node.textContent);

  const mountWithAllItems = async () => {
    api.getChecklist.mockResolvedValue(makeChecklistSnapshot([
      makeChecklistItem({ id: 'inferred', title: 'Archive the newsletter', status: 'done', done_basis: 'inferred', revision: 4 }),
      makeChecklistItem({ id: 'confirmed', title: 'Send the invoice', status: 'done', done_basis: '', revision: 2 }),
      makeChecklistItem({ id: 'open', title: 'Book a referral', status: 'pending', revision: 1 }),
    ]));
    await act(async () => { root.render(<ChecklistWindow rootTaskId="root-1" />); });
    await act(async () => { openChecklistWindow('root-1'); });
    const all = Array.from(container.querySelectorAll('.checklist-filter')).find(node => node.textContent?.startsWith('All'))!;
    await click(all);
  };

  it('tags only the item that was closed on judgment', async () => {
    await mountWithAllItems();

    expect(rowTags()).toEqual(['Inferred']);
    const row = Array.from(container.querySelectorAll('.checklist-row')).find(node => node.textContent?.includes('Archive the newsletter'))!;
    expect(row.querySelector('.checklist-row__tag')?.textContent).toBe('Inferred');
  });

  it('offers Confirm done and Reopen on an inferred item and sends the matching edits', async () => {
    await mountWithAllItems();
    api.updateChecklistItem.mockResolvedValue({ item: makeChecklistItem(), changed: true });

    await act(async () => { openChecklistWindow('root-1', 'inferred'); });
    expect(container.querySelector('.checklist-detail > .checklist-detail__quiet')?.textContent).toContain('Basil marked this done from what it could see');
    await click(detailButton('Confirm done')!);
    expect(api.updateChecklistItem).toHaveBeenLastCalledWith('root-1', 'inferred', { status: 'done', expected_revision: 4 });

    await click(detailButton('Reopen')!);
    expect(api.updateChecklistItem).toHaveBeenLastCalledWith('root-1', 'inferred', { status: 'pending', expected_revision: 4 });
  });

  it('does not offer them on a confirmed done item or an open one', async () => {
    await mountWithAllItems();

    await act(async () => { openChecklistWindow('root-1', 'confirmed'); });
    expect(detailButton('Confirm done')).toBeUndefined();
    expect(detailButton('Reopen')).toBeUndefined();

    await act(async () => { openChecklistWindow('root-1', 'open'); });
    expect(detailButton('Confirm done')).toBeUndefined();
    expect(container.querySelector('.checklist-detail > .checklist-detail__quiet')).toBeNull();
  });
});
