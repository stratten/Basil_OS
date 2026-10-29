import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail, AgentTaskFollowUp } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend } from './agentHydration';

const ROOT = 'root-chain';
const CANCELED_TURN = 'turn-canceled';
const NEW_TURN = 'turn-new';

function followUp(overrides: Partial<AgentTaskFollowUp>): AgentTaskFollowUp {
  return {
    id: CANCELED_TURN,
    original_prompt: 'Finish removing the four items',
    timestamp: '2026-10-27T19:43:03.000Z',
    status: 'canceled',
    result_message: '',
    files: [],
    reference_paths: [],
    ...overrides,
  } as AgentTaskFollowUp;
}

function chainDetail(followUps: AgentTaskFollowUp[]): AgentTaskDetail {
  return {
    id: ROOT,
    original_prompt: 'Review the five most recent emails',
    transcribed_prompt: 'Review the five most recent emails',
    timestamp: '2026-10-27T19:25:32.000Z',
    status: 'completed',
    result_message: 'Done',
    files: [],
    reference_paths: [],
    follow_ups: followUps,
  };
}

function startFollowUpOnCanceledChain() {
  agentStore.registerAgent(ROOT);
  agentStore.setCurrentTurnTaskId(ROOT, CANCELED_TURN);
  agentStore.updateAgentTaskText(ROOT, 'Finish removing the four items');
  agentStore.updateStatus(ROOT, 'failed');
  agentStore.markCanceled(ROOT);
  agentStore.beginFollowUpTurn(NEW_TURN, ROOT);
}

describe('hydrating a chain whose newest durable turn was canceled while a follow-up has begun', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({ approvals: [], orphaned_approval_ids: [] });
    vi.spyOn(api, 'getPendingCommandInputs').mockResolvedValue({ requests: [] });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('does not re-mark the live follow-up as canceled before the backend has recorded it', async () => {
    startFollowUpOnCanceledChain();
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([followUp({})]));

    await hydrateAgentFromBackend(ROOT);

    const agent = agentStore.getAgent(ROOT);
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.status).toBe('processing');
    expect(agent?.originalPrompt).toBe('');
  });

  it('shows the follow-up as live once the backend reports it in flight', async () => {
    startFollowUpOnCanceledChain();
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(chainDetail([
      followUp({}),
      followUp({ id: NEW_TURN, original_prompt: 'Pivoting back to the document', status: 'processing' }),
    ]));

    await hydrateAgentFromBackend(ROOT);

    const agent = agentStore.getAgent(ROOT);
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.status).toBe('processing');
    expect(agent?.originalPrompt).toBe('Pivoting back to the document');
    expect(agent?.currentTurnTaskId).toBe(NEW_TURN);
  });

  it('still shows a chain whose newest turn is canceled and has no follow-up as canceled', async () => {
    agentStore.registerAgent('plain-root');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue({
      ...chainDetail([followUp({})]),
      id: 'plain-root',
    });

    await hydrateAgentFromBackend('plain-root');

    const agent = agentStore.getAgent('plain-root');
    expect(agent?.isCanceled).toBe(true);
    expect(agent?.status).toBe('failed');
  });

  it('survives the early stale poll, then settles as completed when the follow-up finishes', async () => {
    startFollowUpOnCanceledChain();
    const detailSpy = vi.spyOn(api, 'getAgentTaskDetail');

    detailSpy.mockResolvedValue(chainDetail([followUp({})]));
    await hydrateAgentFromBackend(ROOT);

    detailSpy.mockResolvedValue(chainDetail([
      followUp({}),
      followUp({ id: NEW_TURN, original_prompt: 'Pivoting back to the document', status: 'processing' }),
    ]));
    await hydrateAgentFromBackend(ROOT);

    detailSpy.mockResolvedValue({
      ...chainDetail([]),
      id: NEW_TURN,
      original_prompt: 'Pivoting back to the document',
      status: 'completed',
      result_message: 'The SOW now matches the scope.',
    });
    await hydrateActiveFollowUpChild(ROOT, NEW_TURN);

    const agent = agentStore.getAgent(ROOT);
    expect(agent?.isCanceled).toBe(false);
    expect(agent?.status).toBe('completed');
    expect(agent?.result).toBe('The SOW now matches the scope.');
    expect(agentStore.hasActiveFollowUpTurn(ROOT)).toBe(false);
  });
});
