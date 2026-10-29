// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail, RegisterNewAgentMessage } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { useHostBridge } from './useHostBridge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/websocket', () => ({
  wsManager: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onConnect: vi.fn(),
    subscribe: vi.fn(() => () => undefined),
    subscribeConnectionState: vi.fn(() => () => undefined),
  },
}));

let p = '';
let counter = 0;
let root: Root | null = null;
let container: HTMLDivElement | null = null;

function Harness() {
  useHostBridge({
    setSidebarExpanded: vi.fn(),
    setCaptureState: vi.fn(),
    setInitialized: vi.fn(),
    setInitiallyProcessing: vi.fn(),
    setViewedDetail: vi.fn(),
    setSelectedScheduledAgentTaskId: vi.fn(),
    setCreateScheduledMode: vi.fn(),
    setMissedRunToasts: vi.fn(),
    setDetachedRootTaskId: vi.fn(),
    setDetachedRootsElsewhere: vi.fn(),
    viewedDetailRef: { current: null },
    onValidationRunStateRequest: vi.fn(),
    onValidationRunFocus: vi.fn(),
    onValidationManagedHistoryRestore: vi.fn(),
  });
  return null;
}

function turn(id: string, sequence: number, previousId: string) {
  return {
    id,
    original_prompt: `prompt ${id}`,
    timestamp: `2026-10-24T13:0${sequence}:00.000Z`,
    status: 'completed',
    result_message: `answer ${id}`,
    files: [],
    reference_paths: [],
    root_task_id: `${p}chain-root`,
    previous_task_id: previousId,
    chain_sequence_number: sequence,
  };
}

function chainRootDetail(): AgentTaskDetail {
  return {
    id: `${p}chain-root`,
    original_prompt: 'prompt chain-root',
    transcribed_prompt: 'prompt chain-root',
    timestamp: '2026-10-24T13:00:00.000Z',
    status: 'completed',
    result_message: 'answer chain-root',
    files: [],
    reference_paths: [],
    root_task_id: `${p}chain-root`,
    follow_ups: [turn(`${p}turn-1`, 1, `${p}chain-root`), turn(`${p}turn-2`, 2, `${p}turn-1`)],
  } as unknown as AgentTaskDetail;
}

function turnDetail(): AgentTaskDetail {
  return { ...turn(`${p}turn-2`, 2, `${p}turn-1`), transcribed_prompt: 'prompt turn-2', follow_ups: [] } as unknown as AgentTaskDetail;
}

function registerFromNative(message: RegisterNewAgentMessage) {
  const bridge = (window as unknown as { basilAgentTask: { onRegisterNewAgent: (data: RegisterNewAgentMessage) => void } }).basilAgentTask;
  bridge.onRegisterNewAgent(message);
}

async function flush() {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

describe('native register-new-agent handler for a hotkey follow-up', () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    counter += 1;
    p = `h${counter}-`;
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
    vi.spyOn(api, 'getAgentTaskDetail').mockImplementation(async (id: string) => {
      if (id === `${p}chain-root`) return chainRootDetail();
      if (id === `${p}turn-2`) return turnDetail();
      throw new Error(`unexpected detail request for ${id}`);
    });
    container = document.createElement('div');
    root = createRoot(container);
    await act(async () => {
      root!.render(<Harness />);
    });
  });

  afterEach(async () => {
    await act(async () => {
      root?.unmount();
    });
    root = null;
    container = null;
  });

  it('folds the new turn onto the chain root when the focused entry was keyed by a turn id', async () => {
    agentStore.registerAgent(`${p}turn-2`);
    agentStore.updateStatus(`${p}turn-2`, 'completed');
    agentStore.selectAgent(`${p}turn-2`);

    registerFromNative({ agentTaskId: `${p}turn-3`, rootTaskId: `${p}turn-2`, previousTaskId: `${p}turn-2` });
    await flush();

    expect(agentStore.getAllAgents().map(agent => agent.agentTaskId)).toEqual([`${p}chain-root`]);
    const agent = agentStore.getAgent(`${p}chain-root`);
    expect(agent?.currentTurnTaskId).toBe(`${p}turn-3`);
    expect(agent?.status).toBe('processing');
    expect(agent?.previousTaskId).toBe(`${p}turn-2`);
    expect(agentStore.getSelectedAgentId()).toBe(`${p}chain-root`);
  });

  it('still loads the earlier turns when the live feed announced the turn while the root was being resolved', async () => {
    agentStore.registerAgent(`${p}turn-2`);
    agentStore.updateStatus(`${p}turn-2`, 'completed');
    agentStore.selectAgent(`${p}turn-2`);

    registerFromNative({ agentTaskId: `${p}turn-3`, rootTaskId: `${p}turn-2`, previousTaskId: `${p}turn-2` });
    agentStore.handleWSEvent({
      event_type: 'agent_task_progress',
      agent_task_id: `${p}turn-3`,
      root_task_id: `${p}chain-root`,
      status: 'processing',
      details: 'Started',
    });
    await flush();

    const agent = agentStore.getAgent(`${p}chain-root`);
    expect(agent?.currentTurnTaskId).toBe(`${p}turn-3`);
    expect(agent?.agentTaskHistory.map(item => item.id)).toEqual([`${p}chain-root`, `${p}turn-1`, `${p}turn-2`]);
  });

  it('registers a fresh top-level agent when there is no parent', async () => {
    registerFromNative({ agentTaskId: `${p}fresh` });
    await flush();

    expect(agentStore.getAgent(`${p}fresh`)?.status).toBe('processing');
    expect(agentStore.getSelectedAgentId()).toBe(`${p}fresh`);
  });
});
