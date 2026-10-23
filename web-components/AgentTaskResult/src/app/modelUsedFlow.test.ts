import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail, AgentTaskFollowUp } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { AgentStore } from '../store/agentStore/websocketHandlers';
import { mapDetailToDisplayable } from '../components/sidebar/sidebarUtils';
import { deriveAgentTaskRunFocusSummaries } from '../components/run/agentTaskRunFocus';
import { buildDurableFollowUpHistoryBeforeActiveChild } from './followUpHistory';
import { hydrateAgentFromBackend } from './agentHydration';

function followUp(overrides: Partial<AgentTaskFollowUp> = {}): AgentTaskFollowUp {
  return {
    id: 'follow-up-1',
    original_prompt: 'And the appendix?',
    timestamp: '2026-10-01T12:05:00.000Z',
    status: 'completed',
    result_message: 'Appendix summarized.',
    files: [],
    reference_paths: [],
    chain_sequence_number: 1,
    ...overrides,
  };
}

function detail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 'root-task',
    original_prompt: 'Summarize the report',
    transcribed_prompt: 'Summarize the report',
    timestamp: '2026-10-01T12:00:00.000Z',
    status: 'completed',
    result_message: 'Report summarized.',
    files: [],
    reference_paths: [],
    follow_ups: [],
    ...overrides,
  };
}

describe('model used in the agent store', () => {
  it('records the answering model and ignores an absent value', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');

    store.updateModelUsed('task-1', 'gpt-5-mini');
    store.updateModelUsed('task-1', undefined);

    expect(store.getAgent('task-1')?.modelUsed).toBe('gpt-5-mini');
  });

  it('snapshots the answering model into history and clears it for the next turn', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.updateAgentTaskText('task-1', 'Summarize the report');
    store.setResult('task-1', 'Report summarized.', []);
    store.updateModelUsed('task-1', 'gpt-5-mini');

    store.beginFollowUpTurn('follow-up-1', 'task-1');

    const agent = store.getAgent('task-1');
    expect(agent?.agentTaskHistory[0]?.modelUsed).toBe('gpt-5-mini');
    expect(agent?.modelUsed).toBeUndefined();
  });

  it('falls back to the explicit override when snapshotting a run with no recorded model', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.updateAgentTaskText('task-1', 'Summarize the report');
    store.setResult('task-1', 'Report summarized.', []);
    store.updateOriginalModelId('task-1', 'local-qwen-3.5');

    store.beginFollowUpTurn('follow-up-1', 'task-1');

    expect(store.getAgent('task-1')?.agentTaskHistory[0]?.modelUsed).toBe('local-qwen-3.5');
  });

  it('clears the previous attempt model when a retry begins', () => {
    const store = new AgentStore();
    store.registerAgent('task-1');
    store.updateModelUsed('task-1', 'gpt-5-mini');

    store.resetForRetry('task-1');

    expect(store.getAgent('task-1')?.modelUsed).toBeUndefined();
  });
});

describe('model used in detail mapping', () => {
  it('maps a root-only detail and prefers model_used over the override for history', () => {
    const mapped = mapDetailToDisplayable(detail({ model_used: 'gpt-5-mini', model_id: 'local-qwen-3.5' }));

    expect(mapped.modelUsed).toBe('gpt-5-mini');
    expect(mapped.originalModelId).toBe('local-qwen-3.5');
  });

  it('leaves modelUsed unset when nothing was recorded', () => {
    expect(mapDetailToDisplayable(detail()).modelUsed).toBeUndefined();
  });

  it('carries each turn model into history and the latest turn model onto the display', () => {
    const mapped = mapDetailToDisplayable(detail({
      model_used: 'claude-sonnet-4',
      follow_ups: [
        followUp({ id: 'follow-up-1', model_used: 'gpt-5-mini' }),
        followUp({ id: 'follow-up-2', model_used: 'local-qwen-3.5', chain_sequence_number: 2 }),
        followUp({ id: 'follow-up-3', chain_sequence_number: 3, model_id: 'gpt-5-mini' }),
      ],
    }));

    expect(mapped.agentTaskHistory.map(item => item.modelUsed)).toEqual([
      'claude-sonnet-4',
      'gpt-5-mini',
      'local-qwen-3.5',
    ]);
    expect(mapped.modelUsed).toBeUndefined();
    expect(mapped.originalModelId).toBe('gpt-5-mini');
  });

  it('falls back to the explicit override for a historical turn that predates the recording', () => {
    const mapped = mapDetailToDisplayable(detail({
      model_id: 'local-qwen-3.5',
      follow_ups: [followUp({ id: 'follow-up-1' }), followUp({ id: 'follow-up-2', chain_sequence_number: 2 })],
    }));

    expect(mapped.agentTaskHistory[0]?.modelUsed).toBe('local-qwen-3.5');
    expect(mapped.agentTaskHistory[1]?.modelUsed).toBeUndefined();
  });

  it('projects durable history before an active follow-up with each turn model', () => {
    const history = buildDurableFollowUpHistoryBeforeActiveChild(
      detail({
        model_used: 'claude-sonnet-4',
        follow_ups: [followUp({ id: 'follow-up-1', model_used: 'gpt-5-mini' }), followUp({ id: 'active', chain_sequence_number: 2 })],
      }),
      'active',
    );

    expect(history.map(item => item.modelUsed)).toEqual(['claude-sonnet-4', 'gpt-5-mini']);
  });
});

describe('model used in run focus summaries', () => {
  it('exposes the model for historical runs and the current run', () => {
    const displayable = mapDetailToDisplayable(detail({
      model_used: 'claude-sonnet-4',
      follow_ups: [followUp({ id: 'follow-up-1', model_used: 'gpt-5-mini' })],
    }));

    const runs = deriveAgentTaskRunFocusSummaries({ ...displayable, modelUsed: 'gpt-5-mini' }, false);

    expect(runs.map(run => run.modelUsed)).toEqual(['claude-sonnet-4', 'gpt-5-mini']);
  });
});

describe('model used during hydration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({
      approvals: [],
      orphaned_approval_ids: [],
    });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('applies the recorded model of a run that just finished', async () => {
    agentStore.registerAgent('hydrate-model-task');
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(detail({
      id: 'hydrate-model-task',
      model_used: 'gpt-5-mini',
    }));

    hydrateAgentFromBackend('hydrate-model-task');

    await vi.waitFor(() => {
      expect(agentStore.getAgent('hydrate-model-task')?.modelUsed).toBe('gpt-5-mini');
    });
  });
});
