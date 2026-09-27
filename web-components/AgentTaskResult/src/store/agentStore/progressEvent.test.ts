import { describe, expect, it } from 'vitest';
import { parseProgressEvent } from './progressEvent';

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
      event_type: 'agentTask_progress',
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
