import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';

// bridge.ts (imported by useHostBridge.ts) assigns onto `window` at module load time and the test environment has no jsdom, so `window` is stubbed before the first import (same pattern as hydrateDetachedChain.test.ts).
let resolveFollowUpTarget: typeof import('./useHostBridge').resolveFollowUpTarget;

// The store keeps follow-up mappings after an entry is removed, so every test uses its own ids.
let p = '';
let testCounter = 0;

beforeAll(async () => {
  vi.stubGlobal('window', { setTimeout: () => 0 });
  resolveFollowUpTarget = (await import('./useHostBridge')).resolveFollowUpTarget;
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

describe('resolveFollowUpTarget', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    testCounter += 1;
    p = `t${testCounter}-`;
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
  });

  it('resolves the real chain root when the selected entry is keyed by a non-root turn', async () => {
    mockDetails();
    completedAgent(`${p}turn-2`);

    const target = await resolveFollowUpTarget(`${p}turn-2`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}turn-2` });
    expect(agentStore.getAgent(`${p}turn-2`)).toBeUndefined();
    expect(agentStore.getSelectedAgentId()).toBe(`${p}chain-root`);
    expect(agentStore.getAgent(`${p}chain-root`)?.agentTaskHistory.map(item => item.id)).toEqual([`${p}chain-root`, `${p}turn-1`]);
  });

  it('keeps every earlier turn visible after the follow-up begins on the resolved root', async () => {
    mockDetails();
    completedAgent(`${p}turn-2`);

    const { parentId, previousTaskId } = await resolveFollowUpTarget(`${p}turn-2`);
    agentStore.beginFollowUpTurn(`${p}turn-3`, parentId, undefined, previousTaskId);

    const agent = agentStore.getAgent(`${p}chain-root`);
    expect(agent?.agentTaskHistory.map(item => item.id)).toEqual([`${p}chain-root`, `${p}turn-1`, `${p}turn-2`]);
    expect(agent?.currentTurnTaskId).toBe(`${p}turn-3`);
    expect(agentStore.getAgent(`${p}turn-2`)).toBeUndefined();
  });

  it('reuses an existing root-keyed entry instead of reseeding it', async () => {
    mockDetails();
    completedAgent(`${p}chain-root`);
    completedAgent(`${p}turn-2`);
    agentStore.setCurrentTurnTaskId(`${p}chain-root`, `${p}turn-2`);

    const target = await resolveFollowUpTarget(`${p}turn-2`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}turn-2` });
    expect(agentStore.getAgent(`${p}turn-2`)).toBeUndefined();
    expect(agentStore.getSelectedAgentId()).toBe(`${p}chain-root`);
  });

  it('leaves a genuine root task untouched', async () => {
    const detailSpy = vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue({
      ...rootDetail(),
      follow_ups: [],
    });
    completedAgent(`${p}chain-root`);

    const target = await resolveFollowUpTarget(`${p}chain-root`);

    expect(target).toEqual({ parentId: `${p}chain-root`, previousTaskId: `${p}chain-root` });
    expect(detailSpy).toHaveBeenCalledTimes(1);
    expect(agentStore.getAgent(`${p}chain-root`)).toBeDefined();
  });

  it('does not fetch anything for an entry that already knows its chain', async () => {
    const detailSpy = vi.spyOn(api, 'getAgentTaskDetail');
    completedAgent(`${p}chain-root`);
    agentStore.beginFollowUpTurn(`${p}turn-1`, `${p}chain-root`, undefined, `${p}chain-root`);

    const target = await resolveFollowUpTarget(`${p}chain-root`);

    expect(target.parentId).toBe(`${p}chain-root`);
    expect(detailSpy).not.toHaveBeenCalled();
  });

  it('falls back to the selected id when the backend cannot be reached', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockRejectedValue(new Error('offline'));
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    completedAgent(`${p}turn-2`);

    const target = await resolveFollowUpTarget(`${p}turn-2`);

    expect(target).toEqual({ parentId: `${p}turn-2`, previousTaskId: `${p}turn-2` });
    expect(agentStore.getAgent(`${p}turn-2`)).toBeDefined();
  });
});
