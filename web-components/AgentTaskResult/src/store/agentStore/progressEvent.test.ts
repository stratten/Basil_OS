import { describe, expect, it } from 'vitest';
import { parseProgressEvent, timedOutInteractionId } from './progressEvent';

describe('parseProgressEvent', () => {
  it('uses a canonical timeline_entry and its progress metadata', () => {
    const parsed = parseProgressEvent({
      event_type: 'agent_progress_update',
      timeline_entry: {
        id: 'phase-2',
        type: 'step',
        timestamp: '2026-07-13T12:00:00Z',
        content: 'Searching contacts',
        metadata: {
          progress_phase: 'Researching',
          progress_current: 2,
          progress_total: 4,
          progress_status: 'in_progress',
        },
      },
    });

    expect(parsed.currentPhase).toBe('Researching');
    expect(parsed.timelineEntry?.id).toBe('phase-2');
    expect(parsed.progressStep).toMatchObject({
      step: 'Searching contacts',
      isActive: true,
      isComplete: false,
    });
  });

  it('preserves legacy top-level progress events as a step fallback', () => {
    const parsed = parseProgressEvent({
      event_type: 'agent_task_progress',
      step: 'Preparing request',
      status: 'completed',
    });

    expect(parsed.timelineEntry).toBeUndefined();
    expect(parsed.progressStep).toMatchObject({
      step: 'Preparing request',
      isActive: false,
      isComplete: true,
    });
  });

  it('reads a nested legacy dynamic step', () => {
    const parsed = parseProgressEvent({
      event_type: 'dynamic_step_added',
      payload: { step: { description: 'Inspect calendar' } },
      status: 'started',
    });

    expect(parsed.progressStep).toMatchObject({
      step: 'Inspect calendar',
      isActive: true,
    });
  });
});

describe('timedOutInteractionId', () => {
  const entry = (status: string, interactionId: unknown = 'approval-1') => ({
    id: 'user_interaction_approval-1',
    type: 'step' as const,
    timestamp: '2026-10-04T23:42:00+00:00',
    content: 'git status',
    detail_kind: 'user_interaction',
    metadata: { user_interaction: { interaction_id: interactionId, kind: 'approval', status } },
  });

  it('names the request only for a timed-out exchange', () => {
    expect(timedOutInteractionId(entry('timed_out'))).toBe('approval-1');
    expect(timedOutInteractionId(entry('approved'))).toBeNull();
    expect(timedOutInteractionId(entry('waiting'))).toBeNull();
    expect(timedOutInteractionId(entry('timed_out', ''))).toBeNull();
    expect(timedOutInteractionId({ ...entry('timed_out'), detail_kind: 'step_note' })).toBeNull();
    expect(timedOutInteractionId({ ...entry('timed_out'), metadata: undefined })).toBeNull();
  });
});
