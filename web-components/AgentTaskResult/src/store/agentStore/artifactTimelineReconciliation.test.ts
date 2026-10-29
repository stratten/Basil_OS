import { describe, expect, it } from 'vitest';
import type { AgentTaskArtifactHttpResponse } from '../../artifacts/artifactContract';
import { deriveAgentTaskArtifacts } from '../../components/artifacts/artifactDerivation';
import type { StructuredFile, TimelineEntry, WSEvent } from '../../types';
import {
  parseAgentTaskArtifactEvent,
  reconcileDurableArtifactEntries,
} from './artifactTimelineReconciliation';
import { AgentStore } from './websocketHandlers';

const artifact = {
  artifact_id: 'file-0123456789abcdef01234567',
  display_name: 'report.md',
  local_path: '/tmp/report.md',
  artifact_kind: 'file',
  operation: 'modify',
  lifecycle: 'verified',
  source_timeline_entry_id: 'artifact_file-0123456789abcdef01234567',
  source_step_id: 'step-write',
  preview: { capability: 'unknown' },
  verification: { status: 'verified', summary: 'Verified 13 bytes.' },
} satisfies AgentTaskArtifactHttpResponse;

function artifactEvent(overrides: Record<string, unknown> = {}): WSEvent {
  return {
    event_type: 'agent_task_artifact',
    agent_task_id: 'task-artifact',
    agent_task_artifact: artifact,
    timeline_entry: {
      id: artifact.source_timeline_entry_id,
      type: 'artifact',
      timestamp: '2026-08-10T00:00:00.000Z',
      content: 'Ignored transport content',
      detail_kind: 'artifact',
      summary: 'Ignored transport summary',
      body: 'Ignored transport body',
      metadata: {
        event_type: 'agent_task_artifact',
        raw_detail: true,
        artifact,
        content: 'must not enter client state',
      },
      streaming: false,
    },
    ...overrides,
  };
}

function artifactEntry(overrides: Record<string, unknown> = {}): TimelineEntry {
  return parseAgentTaskArtifactEvent(artifactEvent(overrides)) as TimelineEntry;
}

describe('Slice 4B artifact timeline acceptance', () => {
  it('copies only the selected event fields into one provisional timeline entry', () => {
    expect(parseAgentTaskArtifactEvent(artifactEvent())).toEqual({
      id: 'artifact_file-0123456789abcdef01234567',
      type: 'artifact',
      timestamp: '2026-08-10T00:00:00.000Z',
      content: 'Verified local file: report.md',
      step_id: 'step-write',
      correlation_id: 'step-write',
      detail_kind: 'artifact',
      summary: 'Verified local file: report.md',
      body: 'Verified 13 bytes.',
      metadata: {
        event_type: 'agent_task_artifact',
        raw_detail: true,
        artifact,
      },
      streaming: false,
    });
  });

  it('rejects malformed, mismatched, and non-4B artifact events', () => {
    expect(parseAgentTaskArtifactEvent(artifactEvent({
      agent_task_artifact: { ...artifact, verification: { status: 'failed', summary: 'Failed.' } },
    }))).toBeUndefined();
    expect(parseAgentTaskArtifactEvent(artifactEvent({
      timeline_entry: {
        ...(artifactEvent().timeline_entry as Record<string, unknown>),
        id: 'wrong-entry-id',
      },
    }))).toBeUndefined();
    expect(parseAgentTaskArtifactEvent(artifactEvent({
      agent_task_artifact: { ...artifact, artifact_id: 'artifact-report' },
    }))).toBeUndefined();
  });

  it('rejects a malformed artifact before it can create or reroute an agent task', () => {
    const store = new AgentStore();

    store.handleWSEvent(artifactEvent({
      root_task_id: 'root-task',
      agent_task_artifact: { ...artifact, artifact_id: 'artifact-report' },
    }));

    expect(store.getAgent('task-artifact')).toBeUndefined();
    expect(store.getAgent('root-task')).toBeUndefined();
  });

  it('routes accepted evidence without changing terminal or canceled lifecycle state', () => {
    const store = new AgentStore();
    store.registerAgent('task-artifact');
    store.handleWSEvent(artifactEvent());
    store.handleWSEvent({
      event_type: 'agent_task_canceled',
      agent_task_id: 'task-artifact',
      message: 'Canceled after write',
    });
    store.handleWSEvent(artifactEvent());

    const agent = store.getAgent('task-artifact');
    expect(agent?.isCanceled).toBe(true);
    expect(agent?.executionTimeline).toEqual([artifactEntry()]);
  });

  it('replaces a same-ID live entry without retaining unselected metadata', () => {
    const store = new AgentStore();
    store.registerAgent('task-artifact');
    store.upsertTimelineEntry('task-artifact', {
      ...artifactEntry(),
      metadata: {
        event_type: 'agent_task_artifact',
        raw_detail: true,
        artifact,
        receipt: 'must not survive replacement',
      },
    });

    store.handleWSEvent(artifactEvent());

    expect(store.getAgent('task-artifact')?.executionTimeline).toEqual([artifactEntry()]);
  });

  it('replaces a same-ID live entry with durable evidence while preserving an omitted provisional entry', () => {
    const live = artifactEntry();
    const durableFailed = artifactEntry({
      agent_task_artifact: {
        ...artifact,
        lifecycle: 'failed',
        verification: { status: 'failed', summary: 'Verification failed.' },
      },
      timeline_entry: {
        ...(artifactEvent().timeline_entry as Record<string, unknown>),
        metadata: {
          event_type: 'agent_task_artifact',
          raw_detail: true,
          artifact: {
            ...artifact,
            lifecycle: 'failed',
            verification: { status: 'failed', summary: 'Verification failed.' },
          },
        },
      },
    });

    expect(reconcileDurableArtifactEntries([live], [])).toEqual([live]);
    expect(reconcileDurableArtifactEntries([live], [durableFailed])).toEqual([durableFailed]);
  });

  it('deduplicates an accepted live artifact with a finalizer file through existing Slice 1A derivation', () => {
    const file: StructuredFile = {
      name: 'report.md',
      path: '/tmp/report.md',
      artifact: {
        ...artifact,
        lifecycle: 'ready',
        verification: { status: 'unknown' },
      },
    };
    const result = deriveAgentTaskArtifacts([file], [artifactEntry()]);

    expect(result.produced).toHaveLength(1);
    expect(result.produced[0]).toMatchObject({
      artifactId: artifact.artifact_id,
      lifecycle: 'verified',
      verification: { status: 'verified', summary: 'Verified 13 bytes.' },
    });
  });
});
