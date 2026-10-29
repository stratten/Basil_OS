import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskDetail, TimelineEntry } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { liveGapStart, markLiveFeedLost, noteLiveEvent, resetLiveActivityClockForTests } from '../store/liveActivityClock';
import { hydrateAgentFromBackend } from './agentHydration';

const T0 = Date.parse('2026-10-27T15:00:00.000Z');
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString();

function step(id: string, content: string, seconds: number): TimelineEntry {
  return { id, type: 'step', content, timestamp: at(seconds) };
}

function inFlightDetail(taskId: string, timeline: TimelineEntry[]): AgentTaskDetail {
  return {
    id: taskId,
    original_prompt: 'Check disk usage',
    transcribed_prompt: 'Check disk usage',
    timestamp: at(0),
    status: 'processing',
    files: [],
    reference_paths: [],
    follow_ups: [],
    execution_timeline: timeline,
  } as AgentTaskDetail;
}

function localContents(taskId: string): string[] {
  return (agentStore.getAgent(taskId)?.executionTimeline ?? []).map(entry => entry.content);
}

describe('hydrateAgentFromBackend progress backfill', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetLiveActivityClockForTests();
    vi.spyOn(api, 'getPendingExecutionApprovals').mockResolvedValue({ approvals: [], orphaned_approval_ids: [] });
    vi.spyOn(api, 'getPendingProviderInteraction').mockResolvedValue({ interaction: null });
  });

  it('merges progress that arrived while the live feed was down and then clears the gap', async () => {
    const taskId = 'gap-task';
    agentStore.registerAgent(taskId);
    agentStore.upsertTimelineEntry(taskId, step('live-1', 'Planning', 0));
    noteLiveEvent(taskId, T0);
    markLiveFeedLost();
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(inFlightDetail(taskId, [
      step('db-1', 'Planning', 0.2),
      step('db-2', 'Ran a shell command', 20),
      step('db-3', 'Read the command output', 30),
    ]));

    await hydrateAgentFromBackend(taskId);

    expect(localContents(taskId)).toEqual(['Planning', 'Ran a shell command', 'Read the command output']);
    expect(liveGapStart(taskId)).toBeUndefined();
  });

  it('leaves a task whose live feed never broke exactly as it is', async () => {
    const taskId = 'no-gap-task';
    agentStore.registerAgent(taskId);
    agentStore.upsertTimelineEntry(taskId, step('live-1', 'Live wording of the step', 5));
    noteLiveEvent(taskId, T0 + 5000);
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(inFlightDetail(taskId, [
      step('db-1', 'Different persisted wording', 5.1),
    ]));

    await hydrateAgentFromBackend(taskId);

    expect(localContents(taskId)).toEqual(['Live wording of the step']);
  });

  it('shows persisted progress in a window that opened mid-run and has nothing yet', async () => {
    const taskId = 'opened-mid-run';
    agentStore.registerAgent(taskId);
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(inFlightDetail(taskId, [
      step('db-1', 'Analyzing request', 0),
      step('db-2', 'Using shell service', 10),
    ]));

    await hydrateAgentFromBackend(taskId);

    expect(localContents(taskId)).toEqual(['Analyzing request', 'Using shell service']);
  });

  it('keeps the gap open when the task has no persisted progress to merge', async () => {
    const taskId = 'empty-durable';
    agentStore.registerAgent(taskId);
    agentStore.upsertTimelineEntry(taskId, step('live-1', 'Planning', 0));
    noteLiveEvent(taskId, T0);
    markLiveFeedLost();
    vi.spyOn(api, 'getAgentTaskDetail').mockResolvedValue(inFlightDetail(taskId, []));

    await hydrateAgentFromBackend(taskId);

    expect(liveGapStart(taskId)).toBe(T0);
  });
});
