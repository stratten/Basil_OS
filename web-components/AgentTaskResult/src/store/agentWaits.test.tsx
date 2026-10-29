// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

import { resetAgentWaitsForTests, useAgentWait } from './agentWaits';

function Probe({ taskId }: { taskId: string }) {
  const wait = useAgentWait(taskId);
  return <div data-testid="probe">{wait ? `${wait.resumeAtMs}|${wait.reason}` : 'none'}</div>;
}

describe('useAgentWait', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    resetAgentWaitsForTests();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const probeText = () => container.querySelector('[data-testid="probe"]')?.textContent;
  const send = (event: Record<string, unknown>) => act(() => {
    wsHandlers.forEach(handler => handler(event as unknown as WSEvent));
  });

  it('tracks a wait from its start event until its finish event, per task', () => {
    act(() => root.render(<Probe taskId="task-1" />));
    expect(probeText()).toBe('none');

    send({ event_type: 'agent_wait_started', wait_task_id: 'task-2', resume_at_epoch_ms: 5000, reason: 'other task' });
    expect(probeText()).toBe('none');

    send({ event_type: 'agent_wait_started', wait_task_id: 'task-1', resume_at_epoch_ms: 1234567, reason: 'build' });
    expect(probeText()).toBe('1234567|build');

    send({ event_type: 'agent_wait_finished', wait_task_id: 'task-1' });
    expect(probeText()).toBe('none');
  });

  it('drops the wait when the task is canceled and ignores malformed events', () => {
    act(() => root.render(<Probe taskId="task-1" />));
    send({ event_type: 'agent_wait_started', wait_task_id: 'task-1', resume_at_epoch_ms: 'soon', reason: 'bad' });
    send({ event_type: 'agent_wait_started', resume_at_epoch_ms: 5000 });
    expect(probeText()).toBe('none');

    send({ event_type: 'agent_wait_started', wait_task_id: 'task-1', resume_at_epoch_ms: 777, reason: '' });
    expect(probeText()).toBe('777|');
    send({ event_type: 'agent_task_canceled', agent_task_id: 'task-1' });
    expect(probeText()).toBe('none');
  });

  it('drops every countdown after a reconnect', () => {
    act(() => root.render(<Probe taskId="task-1" />));
    send({ event_type: 'agent_wait_started', wait_task_id: 'task-1', resume_at_epoch_ms: 777, reason: 'x' });
    expect(probeText()).toBe('777|x');

    act(() => connectHandlers.forEach(handler => handler()));
    expect(probeText()).toBe('none');
  });
});
