// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../types';
import { makeChecklistItem, makeChecklistSnapshot } from '../components/checklist/checklistTestData';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const getChecklist = vi.fn();
const updateChecklistItem = vi.fn();
vi.mock('../services/api', () => ({ isApiReady: () => true }));
vi.mock('../services/checklistApi', () => ({
  getChecklist: (...args: unknown[]) => getChecklist(...args),
  updateChecklistItem: (...args: unknown[]) => updateChecklistItem(...args),
  isChecklistConflict: (error: unknown) => error instanceof Error && /\(409\)$/.test(error.message),
}));

const wsHandlers: Array<(event: WSEvent) => void> = [];
const connectHandlers: Array<() => void> = [];
vi.mock('../services/websocket', () => ({
  wsManager: {
    subscribe: (handler: (event: WSEvent) => void) => {
      wsHandlers.push(handler);
      return () => wsHandlers.splice(wsHandlers.indexOf(handler), 1);
    },
    onConnect: (handler: () => void) => {
      connectHandlers.push(handler);
      return () => connectHandlers.splice(connectHandlers.indexOf(handler), 1);
    },
  },
}));

import { checklistActions, resetChecklistStoreForTests, useChecklist, useChecklistCounts } from './checklistStore';

function Probe({ rootId = 'root-1', history }: { rootId?: string; history?: { done: number; total: number } }) {
  const { entry } = useChecklist(rootId);
  const counts = useChecklistCounts(rootId, history);
  return (
    <div data-testid="probe" data-state={entry.state}>
      {entry.snapshot?.items.map(item => item.title).join('|') ?? 'none'};{counts.done}/{counts.total};w{counts.waitingUser}
    </div>
  );
}

function CountsOnly({ rootId, history }: { rootId: string; history?: { done: number; total: number } }) {
  const counts = useChecklistCounts(rootId, history);
  return <div data-testid="counts">{counts.done}/{counts.total}</div>;
}

describe('checklist store', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    resetChecklistStoreForTests();
    getChecklist.mockReset();
    updateChecklistItem.mockReset();
    getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem({ title: 'One' }), makeChecklistItem({ id: 'item-2', title: 'Two', status: 'done' })]));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const probe = () => container.querySelector('[data-testid="probe"]')!;
  const counts = () => container.querySelector('[data-testid="counts"]')?.textContent;
  const send = async (event: Record<string, unknown>) => {
    await act(async () => {
      wsHandlers.forEach(handler => handler(event as unknown as WSEvent));
    });
  };

  it('loads a chain when something watches it and reports its counter', async () => {
    await act(async () => { root.render(<Probe />); });

    expect(probe().textContent).toBe('One|Two;1/2;w0');
    expect(probe().getAttribute('data-state')).toBe('ready');
    expect(getChecklist).toHaveBeenCalledWith('root-1');
  });

  it('refetches a watched chain when its update event arrives, and updates the counter from the event itself', async () => {
    await act(async () => { root.render(<Probe />); });
    getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem({ title: 'One', status: 'waiting_user' })]));

    await send({ event_type: 'agent_checklist_updated', root_task_id: 'root-1', counts: { total: 1, done: 0, open: 1, waiting_user: 1, waiting_external: 0, required_open: 0 }, closed_at: null });

    expect(probe().textContent).toBe('One;0/1;w1');
    expect(getChecklist).toHaveBeenCalledTimes(2);
  });

  it('updates the counter for a chain nobody is viewing without fetching it', async () => {
    await act(async () => { root.render(<CountsOnly rootId="other-root" history={{ done: 0, total: 3 }} />); });
    expect(counts()).toBe('0/3');

    await send({ event_type: 'agent_checklist_updated', root_task_id: 'other-root', counts: { total: 3, done: 2, open: 1, waiting_user: 0, waiting_external: 0, required_open: 0 }, closed_at: null });

    expect(counts()).toBe('2/3');
    expect(getChecklist).not.toHaveBeenCalled();
  });

  it('ignores unrelated events and refetches every watched chain after a reconnect', async () => {
    await act(async () => { root.render(<Probe />); });
    getChecklist.mockClear();

    await send({ event_type: 'agent_task_progress', agent_task_id: 'a' });
    await send({ event_type: 'agent_checklist_updated', root_task_id: 'someone-else' });
    expect(getChecklist).not.toHaveBeenCalled();

    await act(async () => { connectHandlers.forEach(handler => handler()); });
    expect(getChecklist).toHaveBeenCalledTimes(1);
  });

  it('lets the newest reply win when an older request answers last', async () => {
    let releaseFirst: (value: unknown) => void = () => {};
    getChecklist.mockReset();
    getChecklist
      .mockImplementationOnce(() => new Promise(resolve => { releaseFirst = resolve; }))
      .mockResolvedValueOnce(makeChecklistSnapshot([makeChecklistItem({ title: 'Newest' })]));
    await act(async () => { root.render(<Probe />); });

    await send({ event_type: 'agent_checklist_updated', root_task_id: 'root-1' });
    await act(async () => { releaseFirst(makeChecklistSnapshot([makeChecklistItem({ title: 'Stale' })])); });

    expect(probe().textContent).toContain('Newest');
    expect(probe().textContent).not.toContain('Stale');
  });

  it('keeps the last snapshot and reports an error when a refresh fails', async () => {
    await act(async () => { root.render(<Probe />); });
    getChecklist.mockRejectedValue(new Error('backend unavailable'));

    await send({ event_type: 'agent_checklist_updated', root_task_id: 'root-1' });

    expect(probe().getAttribute('data-state')).toBe('error');
    expect(probe().textContent).toBe('One|Two;1/2;w0');
  });

  it('shows the history counter until a live one arrives', async () => {
    await act(async () => { root.render(<CountsOnly rootId="row-root" history={{ done: 1, total: 4 }} />); });
    expect(counts()).toBe('1/4');
  });

  it('sends the held revision with an edit and reloads the list afterwards', async () => {
    updateChecklistItem.mockResolvedValue({ item: makeChecklistItem(), changed: true });
    await act(async () => { root.render(<Probe />); });
    getChecklist.mockClear();

    await act(async () => { await checklistActions('root-1').updateItem('item-1', { status: 'done', expected_revision: 1 }); });

    expect(updateChecklistItem).toHaveBeenCalledWith('root-1', 'item-1', { status: 'done', expected_revision: 1 });
    expect(getChecklist).toHaveBeenCalledTimes(1);
  });

  it('reloads the latest list and rethrows when an edit conflicts, and does not reload for other failures', async () => {
    await act(async () => { root.render(<Probe />); });
    getChecklist.mockClear();
    updateChecklistItem.mockRejectedValueOnce(new Error('This changed (409)'));

    await act(async () => {
      await expect(checklistActions('root-1').updateItem('item-1', { title: 'x', expected_revision: 1 })).rejects.toThrow('409');
    });
    expect(getChecklist).toHaveBeenCalledTimes(1);

    getChecklist.mockClear();
    updateChecklistItem.mockRejectedValueOnce(new Error('boom (500)'));
    await act(async () => {
      await expect(checklistActions('root-1').updateItem('item-1', { title: 'y' })).rejects.toThrow('500');
    });
    expect(getChecklist).not.toHaveBeenCalled();
  });
});
