import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail, AgentTaskFollowUp } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateAgentFromBackend, seedDurableFollowUpHistory } from './agentHydration';

const ROOT = 'chain-root';

function followUp(id: string, prompt: string, status = 'completed'): AgentTaskFollowUp {
  return {
    id,
    original_prompt: prompt,
    timestamp: '2026-10-28T16:00:00.000Z',
    status,
    result_message: status === 'completed' ? `answer to ${prompt}` : '',
    files: [],
    reference_paths: [],
  } as unknown as AgentTaskFollowUp;
}

function chainDetail(followUps: AgentTaskFollowUp[]): AgentTaskDetail {
  return {
    id: ROOT,
    original_prompt: 'Set up the Gmail MCP',
    transcribed_prompt: 'Set up the Gmail MCP',
    title: 'Gmail MCP Setup',
    timestamp: '2026-10-28T14:00:00.000Z',
    status: 'completed',
    result_message: 'root done',
    files: [],
    reference_paths: [],
    follow_ups: followUps,
  } as unknown as AgentTaskDetail;
}

function historyPrompts(): string[] {
  return (agentStore.getAgent(ROOT)?.agentTaskHistory ?? []).map(item => item.agentTaskText);
}

describe('rebuilding a whole chain when it is opened live', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({ approvals: [], orphaned_approval_ids: [] });
    vi.spyOn(api, 'getPendingCommandInputs').mockResolvedValue({ requests: [] });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
    agentStore.removeAgent(ROOT);
  });

  it('loads every earlier turn while the newest follow-up is still running', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([
      followUp('t1', 'second'),
      followUp('t2', 'third'),
      followUp('t3', 'fourth, still working', 'processing'),
    ]));
    agentStore.registerAgent(ROOT);

    await hydrateAgentFromBackend(ROOT);

    expect(historyPrompts()).toEqual(['Set up the Gmail MCP', 'second', 'third']);
    expect(agentStore.getAgent(ROOT)?.originalPrompt).toBe('fourth, still working');
    expect(agentStore.getAgent(ROOT)?.status).toBe('processing');
  });

  it('loads every turn before the newest one for a finished chain too', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([followUp('t1', 'second'), followUp('t2', 'third')]));
    agentStore.registerAgent(ROOT);

    await hydrateAgentFromBackend(ROOT);

    expect(historyPrompts()).toEqual(['Set up the Gmail MCP', 'second']);
  });

  it('leaves a single-turn task with no history', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([]));
    agentStore.registerAgent(ROOT);

    await hydrateAgentFromBackend(ROOT);

    expect(historyPrompts()).toEqual([]);
  });

  it('never shortens history the entry already holds', async () => {
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([followUp('t1', 'second', 'processing')]));
    agentStore.registerAgent(ROOT);
    agentStore.setAgentTaskHistory(ROOT, [
      { id: 'a', agentTaskText: 'live one', result: 'x', timestamp: '2026-10-28T14:00:00.000Z' },
      { id: 'b', agentTaskText: 'live two', result: 'y', timestamp: '2026-10-28T14:01:00.000Z' },
    ] as never);

    await hydrateAgentFromBackend(ROOT);

    expect(historyPrompts()).toEqual(['live one', 'live two']);
  });
});

describe('seeding earlier turns after a typed follow-up on a live-opened chain', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    agentStore.removeAgent(ROOT);
  });

  it('fills in the earlier turns and excludes the new turn whether or not the backend has recorded it', async () => {
    agentStore.registerAgent(ROOT);
    agentStore.beginFollowUpTurn('t4', ROOT, undefined, 't3');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([
      followUp('t1', 'second'),
      followUp('t2', 'third'),
      followUp('t3', 'fourth'),
    ]));

    await seedDurableFollowUpHistory(ROOT, 't4');

    expect(historyPrompts()).toEqual(['Set up the Gmail MCP', 'second', 'third', 'fourth']);
  });

  it('does nothing when another turn has become current in the meantime', async () => {
    agentStore.registerAgent(ROOT);
    agentStore.beginFollowUpTurn('t5', ROOT, undefined, 't3');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([followUp('t1', 'second')]));

    await seedDurableFollowUpHistory(ROOT, 't4');

    expect(historyPrompts()).toEqual([]);
  });

  it('survives a failed detail request', async () => {
    agentStore.registerAgent(ROOT);
    agentStore.beginFollowUpTurn('t4', ROOT, undefined, 't3');
    vi.spyOn(api, 'getAgentTaskDetail').mockRejectedValue(new Error('offline'));

    await expect(seedDurableFollowUpHistory(ROOT, 't4')).resolves.toBeUndefined();
  });
});
