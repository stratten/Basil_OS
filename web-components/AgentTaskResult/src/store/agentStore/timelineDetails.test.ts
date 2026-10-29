import { describe, expect, it } from 'vitest';
import type { StepDetailEntry, TimelineEntry } from '../../types';
import { AgentStore } from './websocketHandlers';
import { timelineEntryToDetail } from './timelineDetails';

const artifact = {
  artifact_id: 'artifact-report',
  display_name: 'report.md',
  local_path: '/tmp/report.md',
  artifact_kind: 'file',
  operation: 'create',
  lifecycle: 'ready',
  preview: { capability: 'unknown' },
  verification: { status: 'unknown' },
};

function detail(overrides: Partial<StepDetailEntry> = {}): StepDetailEntry {
  return {
    id: 'detail-report',
    timestamp: '2026-08-09T20:00:00Z',
    content: 'Created report.md',
    detail_kind: 'artifact',
    summary: 'Created report.md',
    body: 'Created report.md',
    metadata: { artifact },
    ...overrides,
  };
}

describe('typed artifact detail projection', () => {
  it('projects a valid timeline artifact through the strict parser', () => {
    const entry: TimelineEntry = {
      id: 'timeline-report',
      type: 'step',
      timestamp: '2026-08-09T20:00:00Z',
      content: 'Created report.md',
      detail_kind: 'artifact',
      summary: 'Created report.md',
      body: 'Created report.md',
      metadata: { artifact },
    };

    expect(timelineEntryToDetail(entry)?.artifact).toEqual({
      artifactId: 'artifact-report',
      displayName: 'report.md',
      localPath: '/tmp/report.md',
      artifactKind: 'file',
      operation: 'create',
      lifecycle: 'ready',
      preview: { capability: 'unknown' },
      verification: { status: 'unknown' },
    });
  });

  it('rejects malformed timeline artifact metadata', () => {
    const entry: TimelineEntry = {
      id: 'timeline-broken',
      type: 'step',
      timestamp: '2026-08-09T20:00:00Z',
      content: 'Created report.md',
      detail_kind: 'artifact',
      metadata: { artifact: { artifact_id: 'broken' } },
    };

    expect(timelineEntryToDetail(entry)?.artifact).toBeUndefined();
  });

  it('does not trust a preprojected artifact without valid raw metadata', () => {
    const entry: TimelineEntry = {
      id: 'timeline-preprojected',
      type: 'step',
      timestamp: '2026-08-09T20:00:00Z',
      content: 'Created report.md',
      detail_kind: 'artifact',
      artifact: {
        artifactId: 'artifact-report',
        displayName: 'report.md',
        localPath: '/tmp/report.md',
        artifactKind: 'file',
        lifecycle: 'ready',
        preview: { capability: 'unknown' },
        verification: { status: 'unknown' },
      },
    };

    expect(timelineEntryToDetail(entry)?.artifact).toBeUndefined();
  });

  it('projects an artifact on the direct step-detail ingestion path', () => {
    const store = new AgentStore();
    store.registerAgent('task-report');
    store.upsertStepDetail('task-report', detail());

    expect(store.getAgent('task-report')?.stepDetails[0].artifact?.artifactId).toBe('artifact-report');
    expect(store.getAgent('task-report')?.executionTimeline[0].artifact).toBeUndefined();
  });

  it('clears an invalidated artifact projection when a live detail updates its metadata', () => {
    const store = new AgentStore();
    store.registerAgent('task-report');
    store.upsertStepDetail('task-report', detail());
    store.upsertStepDetail('task-report', detail({
      metadata: { artifact: { artifact_id: 'broken' } },
    }));

    expect(store.getAgent('task-report')?.stepDetails[0].artifact).toBeUndefined();
  });

  it('clears an invalidated artifact projection when a timeline entry updates its metadata', () => {
    const store = new AgentStore();
    store.registerAgent('task-report');
    const entry: TimelineEntry = {
      id: 'timeline-report',
      type: 'step',
      timestamp: '2026-08-09T20:00:00Z',
      content: 'Created report.md',
      detail_kind: 'artifact',
      metadata: { artifact },
    };
    store.upsertTimelineEntry('task-report', entry);
    store.upsertTimelineEntry('task-report', {
      ...entry,
      metadata: { artifact: { artifact_id: 'broken' } },
    });

    expect(store.getAgent('task-report')?.stepDetails[0].artifact).toBeUndefined();
  });
});
