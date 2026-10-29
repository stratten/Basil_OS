import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';

// bridge.ts (imported by useHostBridge.ts) assigns onto `window` at module load time and the test environment has no jsdom, so `window` is stubbed before the first import (same pattern as hydrateDetachedChain.test.ts).
let resolveRegisteredFollowUpTarget: typeof import('./useHostBridge').resolveRegisteredFollowUpTarget;

// The store keeps follow-up mappings after an entry is removed, so every test uses its own ids.
let p = '';
let testCounter = 0;

beforeAll(async () => {
  vi.stubGlobal('window', { setTimeout: () => 0 });
  resolveRegisteredFollowUpTarget = (await import('./useHostBridge')).resolveRegisteredFollowUpTarget;
});

function summary(agentTaskId: string) {
  return {
    agent_task_id: agentTaskId,
    lifecycle: 'completed',
    workflow: {},
    artifacts: [],
    artifact_count: 0,
    verification_status: 'resolved',
    requires_user_attention: false,
  };
}

function turn(id: string, sequence: number, previousId: string, rootId: string) {
  return {
    id,
    original_prompt: `prompt ${id}`,
    timestamp: `2026-10-24T13:0${sequence}:00.000Z`,
    status: 'completed',
    result_message: `answer ${id}`,
    files: [],
    agent_task_presentation_summary: summary(id),
    reference_paths: [],
    root_task_id: rootId,
    previous_task_id: previousId,
    chain_sequence_number: sequence,
  };
}

function rootDetail(): AgentTaskDetail {
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
    follow_ups: [
      turn(`${p}turn-1`, 1, `${p}chain-root`, `${p}chain-root`),
      turn(`${p}turn-2`, 2, `${p}turn-1`, `${p}chain-root`),
    ],
  } as unknown as AgentTaskDetail;
}

function aliasedTurnDetail(): AgentTaskDetail {
  return {
    ...turn(`${p}turn-2`, 2, `${p}turn-1`, `${p}chain-root`),
    transcribed_prompt: 'prompt turn-2',
    follow_ups: [],
  } as unknown as AgentTaskDetail;
}

function mockDetails(): void {
  vi.spyOn(api, 'getAgentTaskDetail').mockImplementation(async (id: string) => {
    if (id === `${p}chain-root`) return rootDetail();
    if (id === `${p}turn-2`) return aliasedTurnDetail();
    throw new Error(`unexpected detail request for ${id}`);
  });
}

function completedAgent(id: string): void {
  agentStore.registerAgent(id);
  agentStore.updateStatus(id, 'completed');
  agentStore.selectAgent(id);
}

describe('resolveRegisteredFollowUpTarget (hotkey follow-up registration)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    testCounter += 1;
    p = `r${testCounter}-`;
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
  });

  it('moves a hotkey follow-up keyed by a turn id onto the chain root and the latest turn', async () => {
    mockDetails();
    completedAgent(`${p}turn-2`);

    const target = await resolveRegisteredFollowUpTarget(`${p}turn-2`, `${p}turn-2`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}turn-2` });
    expect(agentStore.getAgent(`${p}turn-2`)).toBeUndefined();
    expect(agentStore.getSelectedAgentId()).toBe(`${p}chain-root`);
  });

  it('uses the latest known turn instead of the root the hotkey sent as the previous turn', async () => {
    mockDetails();
    completedAgent(`${p}chain-root`);
    agentStore.setCurrentTurnTaskId(`${p}chain-root`, `${p}turn-2`);

    const target = await resolveRegisteredFollowUpTarget(`${p}chain-root`, `${p}chain-root`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}turn-2` });
  });

  it('keeps a previous turn the host explicitly chose', async () => {
    mockDetails();
    completedAgent(`${p}chain-root`);
    agentStore.setCurrentTurnTaskId(`${p}chain-root`, `${p}turn-2`);

    const target = await resolveRegisteredFollowUpTarget(`${p}chain-root`, `${p}turn-1`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}turn-1` });
  });

  it('passes the host values through when the parent has no entry here', async () => {
    const detailSpy = vi.spyOn(api, 'getAgentTaskDetail');

    const target = await resolveRegisteredFollowUpTarget(`${p}unknown`, `${p}unknown`);

    expect(target).toEqual({ parentId: `${p}unknown`, previousTaskId: `${p}unknown` });
    expect(detailSpy).not.toHaveBeenCalled();
  });

  it('falls back to the host values when the backend cannot be reached', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockRejectedValue(new Error('offline'));
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    completedAgent(`${p}turn-2`);

    const target = await resolveRegisteredFollowUpTarget(`${p}turn-2`, `${p}turn-2`);

    expect(target).toEqual({ parentId: `${p}turn-2`, previousTaskId: `${p}turn-2` });
    expect(agentStore.getAgent(`${p}turn-2`)).toBeDefined();
  });

  it('leaves one entry holding the whole chain, with live events from the real root landing on it', async () => {
    mockDetails();
    completedAgent(`${p}turn-2`);
    agentStore.markCanceled(`${p}turn-2`);

    const { parentId, previousTaskId } = await resolveRegisteredFollowUpTarget(`${p}turn-2`, `${p}turn-2`);
    agentStore.beginFollowUpTurn(`${p}turn-3`, parentId, undefined, previousTaskId);
    agentStore.handleWSEvent({
      event_type: 'agent_progress_update',
      agent_task_id: `${p}turn-3`,
      root_task_id: `${p}chain-root`,
      timeline_entry: {
        id: `${p}step`,
        type: 'step',
        timestamp: '2026-10-27T20:18:00Z',
        content: 'Reading the document',
        metadata: { progress_status: 'in_progress' },
      },
    });

    const agents = agentStore.getAllAgents();
    expect(agents.map(agent => agent.agentTaskId)).toEqual([`${p}chain-root`]);
    const agent = agentStore.getAgent(`${p}chain-root`);
    expect(agent?.agentTaskHistory.map(item => item.id)).toEqual([`${p}chain-root`, `${p}turn-1`, `${p}turn-2`]);
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.status).toBe('processing');
    expect(agent?.executionTimeline.map(entry => entry.content)).toContain('Reading the document');
  });
});
