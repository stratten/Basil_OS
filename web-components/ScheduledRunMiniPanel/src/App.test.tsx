// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ActiveRunItem, InitMessage, ScheduledRunRecord } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  initHandler: null as ((config: unknown) => void) | null,
  notifyPanelEmpty: vi.fn(),
  fetchActiveScheduledRuns: vi.fn(),
  fetchScheduledRun: vi.fn(),
}));

vi.mock('./services/bridge', () => ({
  registerInitHandler: (cb: (config: unknown) => void) => { mocks.initHandler = cb; },
  registerThemeHandler: vi.fn(),
  openAgentTaskInResultWidget: vi.fn(),
  dismissRow: vi.fn(),
  dismissPanel: vi.fn(),
  minimizePanel: vi.fn(),
  notifyPanelEmpty: mocks.notifyPanelEmpty,
  notifyReady: vi.fn(),
  requestResize: vi.fn(),
}));

vi.mock('./services/websocket', () => ({
  wsManager: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onConnect: vi.fn(),
    subscribe: vi.fn(() => () => undefined),
  },
}));

vi.mock('./services/api', () => ({
  setBaseUrl: vi.fn(),
  fetchActiveScheduledRuns: mocks.fetchActiveScheduledRuns,
  fetchScheduledRun: mocks.fetchScheduledRun,
}));

vi.mock('@shared/BackendLivenessBanner', () => ({ BackendLivenessBanner: () => null }));

import App from './App';

const RUN_STARTED_LONG_AGO = '2020-01-01T00:00:00Z';

function activeItem(overrides: Partial<ActiveRunItem> = {}): ActiveRunItem {
  return {
    run_id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: 'task-1',
    scheduled_for: RUN_STARTED_LONG_AGO,
    started_at: RUN_STARTED_LONG_AGO,
    title: 'Inbox companion: review recent emails',
    agent_task_text: 'x',
    agent_task_status: 'processing',
    ...overrides,
  };
}

function runRecord(overrides: Partial<ScheduledRunRecord> = {}): ScheduledRunRecord {
  return {
    id: 'run-1',
    scheduled_agent_task_id: 'sched-1',
    agent_task_id: 'task-1',
    status: 'completed',
    agent_task_status: 'completed',
    outcome: 'success',
    verification_status: 'resolved',
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: Root;

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function openPanelWithOneRunningRun() {
  mocks.fetchActiveScheduledRuns.mockResolvedValue([activeItem()]);
  await act(async () => {
    root.render(<App />);
  });
  await act(async () => {
    mocks.initHandler?.({ wsUrl: 'ws://localhost/ws', port: 8000 } satisfies Partial<InitMessage>);
  });
  await advance(0);
}

function rowText(): string {
  return container.querySelector('.mini-panel-rows')?.textContent ?? '';
}

beforeEach(() => {
  vi.useFakeTimers();
  mocks.initHandler = null;
  mocks.notifyPanelEmpty.mockReset();
  mocks.fetchActiveScheduledRuns.mockReset();
  mocks.fetchScheduledRun.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe('a run that ends without the panel hearing about it', () => {
  it('settles on its real result when the backend stops listing it as active, then clears itself', async () => {
    await openPanelWithOneRunningRun();
    expect(rowText()).toContain('Inbox companion: review recent emails');
    expect(rowText()).toContain('Running…');

    mocks.fetchActiveScheduledRuns.mockResolvedValue([]);
    mocks.fetchScheduledRun.mockResolvedValue(runRecord());
    await advance(5000);

    expect(mocks.fetchScheduledRun).toHaveBeenCalledWith('sched-1', 'run-1');
    expect(rowText()).toContain('Completed');
    expect(rowText()).not.toContain('Running…');
    expect(mocks.notifyPanelEmpty).not.toHaveBeenCalled();

    await advance(15000);
    expect(rowText()).toBe('');
    await advance(300);
    expect(mocks.notifyPanelEmpty).toHaveBeenCalledTimes(1);
  });

  it('shows a partial result as partial and keeps it longer than a clean one', async () => {
    await openPanelWithOneRunningRun();

    mocks.fetchActiveScheduledRuns.mockResolvedValue([]);
    mocks.fetchScheduledRun.mockResolvedValue(runRecord({ agent_task_status: 'failed', outcome: 'partial' }));
    await advance(5000);
    expect(rowText()).toContain('Partial result');

    await advance(15000);
    expect(rowText()).toContain('Partial result');
    await advance(45000);
    expect(rowText()).toBe('');
  });

  it('leaves the row alone while the run record still says it is running', async () => {
    await openPanelWithOneRunningRun();

    mocks.fetchActiveScheduledRuns.mockResolvedValue([]);
    mocks.fetchScheduledRun.mockResolvedValue(runRecord({ status: 'running', agent_task_status: 'processing', outcome: null }));
    await advance(5000);

    expect(rowText()).toContain('Running…');
  });

  it('keeps retrying on the next poll when the run record cannot be read', async () => {
    await openPanelWithOneRunningRun();

    mocks.fetchActiveScheduledRuns.mockResolvedValue([]);
    mocks.fetchScheduledRun.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(runRecord());
    await advance(5000);
    expect(rowText()).toContain('Running…');

    await advance(5000);
    expect(rowText()).toContain('Completed');
  });

  it('removes a row whose run the backend no longer knows about', async () => {
    await openPanelWithOneRunningRun();

    mocks.fetchActiveScheduledRuns.mockResolvedValue([]);
    mocks.fetchScheduledRun.mockResolvedValue(null);
    await advance(5000);

    expect(rowText()).toBe('');
  });

  it('does not touch a run the backend still lists as active', async () => {
    await openPanelWithOneRunningRun();

    mocks.fetchActiveScheduledRuns.mockResolvedValue([activeItem()]);
    await advance(5000);

    expect(mocks.fetchScheduledRun).not.toHaveBeenCalled();
    expect(rowText()).toContain('Running…');
  });
});
