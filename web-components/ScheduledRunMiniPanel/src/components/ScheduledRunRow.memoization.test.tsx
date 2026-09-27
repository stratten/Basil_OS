// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, memo } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { MiniPanelRow } from '../types';
import App from '../App';

const testState = vi.hoisted(() => ({
  initHandler: undefined as ((payload: any) => void) | undefined,
  eventHandler: undefined as ((event: Record<string, unknown>) => void) | undefined,
  renderCounts: new Map<string, number>(),
  openAgentTask: vi.fn(),
  dismissRow: vi.fn(),
}));

vi.mock('../services/bridge', () => ({
  registerInitHandler: (handler: (payload: any) => void) => {
    testState.initHandler = handler;
    return () => undefined;
  },
  registerThemeHandler: () => () => undefined,
  openAgentTaskInResultWidget: testState.openAgentTask,
  dismissRow: testState.dismissRow,
  dismissPanel: vi.fn(),
  minimizePanel: vi.fn(),
  notifyPanelEmpty: vi.fn(),
  requestResize: vi.fn(),
}));

vi.mock('../services/websocket', () => ({
  wsManager: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onConnect: vi.fn(),
    subscribe: (handler: (event: Record<string, unknown>) => void) => {
      testState.eventHandler = handler;
      return () => undefined;
    },
  },
}));

vi.mock('../services/api', () => ({
  fetchActiveScheduledRuns: vi.fn(async () => []),
  setBaseUrl: vi.fn(),
}));

vi.mock('./ScheduledRunRow', () => ({
  default: memo(({
    row,
    onOpen,
    onDismiss,
  }: {
    row: MiniPanelRow;
    onOpen: (agentTaskId: string, runId: string) => void;
    onDismiss: (runId: string) => void;
  }) => {
    testState.renderCounts.set(row.runId, (testState.renderCounts.get(row.runId) ?? 0) + 1);
    return (
      <div
        data-testid={`row-${row.runId}`}
        onClick={() => {
          if (row.agentTaskId) onOpen(row.agentTaskId, row.runId);
        }}
      >
        {row.currentStep}
        <button
          type="button"
          aria-label={`Dismiss ${row.runId}`}
          onClick={(event) => {
            event.stopPropagation();
            onDismiss(row.runId);
          }}
        >
          Dismiss
        </button>
      </div>
    );
  }),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

const hydrate = [
  {
    run_id: 'run-1',
    scheduled_agent_task_id: 'scheduled-1',
    agent_task_id: 'agent-1',
    scheduled_for: '2026-08-23T00:00:00.000Z',
    title: 'First',
    agent_task_text: 'First task',
  },
  {
    run_id: 'run-2',
    scheduled_agent_task_id: 'scheduled-2',
    agent_task_id: 'agent-2',
    scheduled_for: '2026-08-23T00:00:00.000Z',
    title: 'Middle',
    agent_task_text: 'Middle task',
  },
  {
    run_id: 'run-3',
    scheduled_agent_task_id: 'scheduled-3',
    agent_task_id: 'agent-3',
    scheduled_for: '2026-08-23T00:00:00.000Z',
    title: 'Third',
    agent_task_text: 'Third task',
  },
];

beforeEach(() => {
  testState.initHandler = undefined;
  testState.eventHandler = undefined;
  testState.renderCounts.clear();
  testState.openAgentTask.mockClear();
  testState.dismissRow.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(<App />);
  });
  act(() => {
    testState.initHandler!({
      wsUrl: 'ws://example.test/ws',
      port: 8000,
      theme: {
        backgroundPrimary: '#fff',
        primary: '#00f',
        secondary: '#111',
        textPrimary: '#000',
      },
      fonts: {
        fontFamily: 'Arial',
        fontFamilyMedium: 'Arial',
        fontFamilyBold: 'Arial',
      },
      hydrate,
    });
  });
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
});

describe('ScheduledRunRow memoization', () => {
  it('isolates unchanged rows and preserves open and dismiss bridge payloads', () => {
    expect(testState.renderCounts).toEqual(new Map([
      ['run-1', 1],
      ['run-2', 1],
      ['run-3', 1],
    ]));

    act(() => {
      testState.eventHandler!({
        event_type: 'agent_progress_update',
        agent_task_id: 'agent-2',
        message: 'Updated middle step',
      });
    });
    expect(testState.renderCounts).toEqual(new Map([
      ['run-1', 1],
      ['run-2', 2],
      ['run-3', 1],
    ]));

    const middle = container.querySelector<HTMLElement>('[data-testid="row-run-2"]')!;
    const dismiss = middle.querySelector<HTMLButtonElement>('button')!;
    act(() => {
      middle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(testState.openAgentTask).toHaveBeenCalledWith('agent-2', 'run-2');

    act(() => {
      dismiss.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(testState.dismissRow).toHaveBeenCalledWith('run-2');
    expect(testState.openAgentTask).toHaveBeenCalledTimes(1);
  });
});
