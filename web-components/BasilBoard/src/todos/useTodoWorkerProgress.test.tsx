import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '@agent-task/types';
import type { TodoWorkAttempt, WSEvent } from '../contracts';
import useTodoWorkerProgress from './useTodoWorkerProgress';

const apiMocks = vi.hoisted(() => ({
  getAgentTaskDetail: vi.fn(),
}));
const websocketMocks = vi.hoisted(() => {
  const handlers: Array<(event: WSEvent) => void> = [];
  const connectHandlers: Array<() => void> = [];
  return {
    handlers,
    connectHandlers,
    subscribe: vi.fn((handler: (event: WSEvent) => void) => {
      handlers.push(handler);
      return () => {
        const index = handlers.indexOf(handler);
        if (index >= 0) handlers.splice(index, 1);
      };
    }),
    onConnect: vi.fn((handler: () => void) => {
      connectHandlers.push(handler);
      return () => {
        const index = connectHandlers.indexOf(handler);
        if (index >= 0) connectHandlers.splice(index, 1);
      };
    }),
  };
});

vi.mock('@agent-task/services/api', () => apiMocks);
vi.mock('../services/websocket', () => ({
  basilBoardWebSocket: websocketMocks,
}));

function attempt(agentTaskId = 'worker-1'): TodoWorkAttempt {
  return {
    agent_task_id: agentTaskId,
    title: 'Worker task',
    status: 'processing',
    created_at: '2026-08-21T12:00:00Z',
    updated_at: '2026-08-21T12:00:00Z',
    attention: false,
  };
}

function taskDetail(id = 'worker-1', status = 'processing'): AgentTaskDetail {
  return {
    id,
    original_prompt: 'Do the work',
    transcribed_prompt: 'Do the work',
    timestamp: '2026-08-21T12:00:00Z',
    status,
    files: [],
    reference_paths: [],
    follow_ups: [],
  };
}

function ProgressHarness({
  attempts,
  onTerminalUpdate,
  onEscalate,
  onStates,
}: {
  attempts: TodoWorkAttempt[];
  onTerminalUpdate: () => void;
  onEscalate: (agentTaskId: string) => void;
  onStates: (states: ReturnType<typeof useTodoWorkerProgress>) => void;
}) {
  const states = useTodoWorkerProgress(attempts, onTerminalUpdate, onEscalate);
  onStates(states);
  return null;
}

describe('useTodoWorkerProgress', () => {
  beforeEach(() => {
    apiMocks.getAgentTaskDetail.mockReset();
    websocketMocks.handlers.splice(0);
    websocketMocks.connectHandlers.splice(0);
    websocketMocks.subscribe.mockClear();
    websocketMocks.onConnect.mockClear();
  });

  it('hydrates matching workers, ignores unrelated events, and updates matching progress', async () => {
    const onStates = vi.fn();
    apiMocks.getAgentTaskDetail.mockResolvedValue(taskDetail());
    render(
      <ProgressHarness attempts={[attempt()]} onStates={onStates} onTerminalUpdate={vi.fn()} onEscalate={vi.fn()} />,
    );
    await waitFor(() => expect(apiMocks.getAgentTaskDetail).toHaveBeenCalledWith('worker-1'));

    websocketMocks.handlers.forEach((handler) => handler({
      event_type: 'agent_task_progress',
      agent_task_id: 'other-worker',
      status_text: 'Ignore this',
    }));
    expect(onStates.mock.calls[onStates.mock.calls.length - 1]?.[0]['worker-1']?.latestActivity).toBeUndefined();

    websocketMocks.handlers.forEach((handler) => handler({
      event_type: 'agent_task_progress',
      agent_task_id: 'worker-1',
      status_text: 'Researching providers',
    }));
    await waitFor(() => expect(onStates.mock.calls[onStates.mock.calls.length - 1]?.[0]['worker-1']?.latestActivity).toBe('Researching providers'));
  });

  it('refreshes durable detail on terminal events and after reconnection', async () => {
    const onTerminalUpdate = vi.fn();
    apiMocks.getAgentTaskDetail.mockResolvedValue(taskDetail());
    render(
      <ProgressHarness attempts={[attempt()]} onStates={vi.fn()} onTerminalUpdate={onTerminalUpdate} onEscalate={vi.fn()} />,
    );
    await waitFor(() => expect(apiMocks.getAgentTaskDetail).toHaveBeenCalledTimes(1));

    websocketMocks.handlers.forEach((handler) => handler({ event_type: 'agent_task_result', agent_task_id: 'worker-1' }));
    await waitFor(() => expect(onTerminalUpdate).toHaveBeenCalledTimes(1));
    websocketMocks.connectHandlers.forEach((handler) => handler());
    await waitFor(() => expect(apiMocks.getAgentTaskDetail).toHaveBeenCalledTimes(3));
  });

  it('opens only once for matching input or approval intervention, never for ordinary progress', async () => {
    const onEscalate = vi.fn();
    apiMocks.getAgentTaskDetail.mockResolvedValue(taskDetail());
    render(
      <ProgressHarness attempts={[attempt()]} onStates={vi.fn()} onTerminalUpdate={vi.fn()} onEscalate={onEscalate} />,
    );
    await waitFor(() => expect(websocketMocks.handlers.length).toBeGreaterThan(0));

    websocketMocks.handlers.forEach((handler) => handler({
      event_type: 'agent_task_progress',
      agent_task_id: 'worker-1',
      status_text: 'Working',
    }));
    expect(onEscalate).not.toHaveBeenCalled();

    const inputEvent = {
      event_type: 'checkpoint_waiting',
      agent_task_id: 'worker-1',
      attention_id: 'input-1',
    };
    websocketMocks.handlers.forEach((handler) => handler(inputEvent));
    websocketMocks.handlers.forEach((handler) => handler(inputEvent));
    websocketMocks.handlers.forEach((handler) => handler({
      event_type: 'execution_approval_request',
      agent_task_id: 'worker-1',
      attention_id: 'approval-1',
    }));
    expect(onEscalate).toHaveBeenCalledTimes(2);
    expect(onEscalate).toHaveBeenNthCalledWith(1, 'worker-1');
    expect(onEscalate).toHaveBeenNthCalledWith(2, 'worker-1');
  });

  it('does not let a stale detail response overwrite a new selected worker', async () => {
    let resolveFirst: (value: AgentTaskDetail) => void = () => {};
    apiMocks.getAgentTaskDetail.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    apiMocks.getAgentTaskDetail.mockResolvedValueOnce(taskDetail('worker-2'));
    const onStates = vi.fn();
    const rendered = render(
      <ProgressHarness attempts={[attempt('worker-1')]} onStates={onStates} onTerminalUpdate={vi.fn()} onEscalate={vi.fn()} />,
    );
    rendered.rerender(
      <ProgressHarness attempts={[attempt('worker-2')]} onStates={onStates} onTerminalUpdate={vi.fn()} onEscalate={vi.fn()} />,
    );
    resolveFirst(taskDetail('worker-1'));
    await waitFor(() => expect(onStates.mock.calls[onStates.mock.calls.length - 1]?.[0]['worker-1']).toBeUndefined());
  });
});
