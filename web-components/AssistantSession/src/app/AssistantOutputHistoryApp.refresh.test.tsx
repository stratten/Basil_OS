import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AssistantOutputHistoryBridgeEvent } from '../bridge/historyTypes';
import type { AssistantOutputHistoryEntry } from '../services/historyApi';
import { initialAssistantSessionState, resolveTheme } from '../state/assistantSessionReducer';
import { AssistantOutputHistoryApp } from './AssistantOutputHistoryApp';

const bridge = vi.hoisted(() => ({
  listeners: [] as Array<(event: unknown) => void>,
}));

vi.mock('../bridge/historyBridge', () => ({
  onHistoryEvent: (listener: (event: unknown) => void) => {
    bridge.listeners.push(listener);
    return () => {
      const index = bridge.listeners.indexOf(listener);
      if (index !== -1) bridge.listeners.splice(index, 1);
    };
  },
  reportHistoryReady: vi.fn(),
  closeWindow: vi.fn(),
  minimizeWindow: vi.fn(),
  toggleChromeCollapse: vi.fn(),
  refineFromHistory: vi.fn(),
  copyHistoryRichText: vi.fn(),
  copyHistoryMarkdown: vi.fn(),
}));

const api = vi.hoisted(() => ({
  fetchHistory: vi.fn(),
  fetchHistoryDetail: vi.fn(),
  deleteHistoryEntry: vi.fn(),
}));

vi.mock('../services/historyApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/historyApi')>()),
  fetchHistory: api.fetchHistory,
  fetchHistoryDetail: api.fetchHistoryDetail,
  deleteHistoryEntry: api.deleteHistoryEntry,
}));

const entry: AssistantOutputHistoryEntry = {
  id: 1,
  outputType: 'assistant_session',
  inputModality: 'voice',
  title: 'First entry',
  outputPreview: 'First preview',
  timestamp: '2026-09-28T13:54:00Z',
  status: 'completed',
  refinementCount: 0,
  appName: 'Mail',
};

function emit(event: AssistantOutputHistoryBridgeEvent) {
  act(() => {
    for (const listener of [...bridge.listeners]) listener(event);
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function renderLoadedApp() {
  const view = render(<AssistantOutputHistoryApp />);
  emit({
    type: 'init',
    baseUrl: 'http://localhost:8000',
    anchoredToWidget: false,
    theme: resolveTheme(initialAssistantSessionState),
  });
  expect(await screen.findByText('First entry')).toBeInTheDocument();
  return view;
}

beforeEach(() => {
  bridge.listeners.splice(0);
  api.fetchHistory.mockReset();
  api.fetchHistoryDetail.mockReset();
  api.deleteHistoryEntry.mockReset();
  api.fetchHistoryDetail.mockReturnValue(new Promise(() => undefined));
});

describe('AssistantOutputHistoryApp refresh continuity', () => {
  it('keeps rows visible and marks the list busy while a background update reloads', async () => {
    const update = deferred<AssistantOutputHistoryEntry[]>();
    api.fetchHistory.mockResolvedValueOnce([entry]).mockReturnValueOnce(update.promise);
    const { container } = await renderLoadedApp();

    emit({ type: 'historyUpdated' });
    expect(screen.getByText('First entry')).toBeInTheDocument();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    expect(container.querySelector('.assistant-output-history-sidebar__list')?.getAttribute('aria-busy')).toBe('true');

    await act(async () => {
      update.resolve([entry]);
      await update.promise;
    });
    expect(container.querySelector('.assistant-output-history-sidebar__list')?.hasAttribute('aria-busy')).toBe(false);
  });

  it('keeps rows and shows no error when a background update fails', async () => {
    api.fetchHistory.mockResolvedValueOnce([entry]).mockRejectedValueOnce(new Error('update failed'));
    await renderLoadedApp();

    emit({ type: 'historyUpdated' });
    await waitFor(() => expect(api.fetchHistory).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('update failed')).not.toBeInTheDocument());
    expect(screen.getByText('First entry')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('shows an inline alert and keeps rows when a delete fails', async () => {
    api.fetchHistory.mockResolvedValueOnce([entry]);
    api.deleteHistoryEntry.mockRejectedValueOnce(new Error('delete failed'));
    const { container } = await renderLoadedApp();

    act(() => { container.querySelector<HTMLButtonElement>('.assistant-output-history-sidebar__delete')!.click(); });
    const confirmButtons = container.querySelectorAll<HTMLButtonElement>('.assistant-output-history-shell__confirm button');
    expect(confirmButtons).toHaveLength(2);
    await act(async () => { confirmButtons[1].click(); });

    expect((await screen.findByRole('alert')).textContent).toContain('delete failed');
    expect(screen.getByText('First entry')).toBeInTheDocument();
    expect(container.querySelector('.assistant-output-history-shell__confirm')).toBeNull();
  });
});
