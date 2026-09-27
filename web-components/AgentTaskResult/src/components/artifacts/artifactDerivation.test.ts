import { describe, expect, it } from 'vitest';
import type { StructuredFile, TimelineEntry } from '../../types';
import { deriveAgentTaskArtifacts } from './artifactDerivation';

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: 'artifact-report',
    display_name: 'report.md',
    local_path: '/tmp/report.md',
    artifact_kind: 'file',
    operation: 'create',
    lifecycle: 'ready',
    preview: { capability: 'unknown' },
    verification: { status: 'unknown' },
    ...overrides,
  };
}

function file(overrides: Record<string, unknown> = {}): StructuredFile {
  return {
    name: 'report.md',
    path: '/tmp/report.md',
    artifact: artifact(),
    ...overrides,
  } as StructuredFile;
}

function entry(overrides: Record<string, unknown> = {}): TimelineEntry {
  return {
    id: 'timeline-report',
    type: 'step',
    timestamp: '2026-08-09T20:00:00Z',
    content: 'Created report.md',
    step_id: 'step-write',
    metadata: { artifact: artifact() },
    ...overrides,
  } as TimelineEntry;
}

describe('deriveAgentTaskArtifacts', () => {
  it('derives deterministic groups from selected finalizer artifacts', () => {
    const result = deriveAgentTaskArtifacts([
      file({ artifact: artifact({ artifact_id: 'created', operation: 'create' }) }),
      file({ artifact: artifact({ artifact_id: 'modified', local_path: '/tmp/modified.md', operation: 'modify' }) }),
      file({ artifact: artifact({ artifact_id: 'overwritten', local_path: '/tmp/overwritten.md', operation: 'overwrite' }) }),
      file({ artifact: artifact({ artifact_id: 'appended', local_path: '/tmp/appended.md', operation: 'append' }) }),
      file({ artifact: artifact({ artifact_id: 'read', local_path: '/tmp/input.md', operation: 'read' }) }),
      file({ artifact: artifact({ artifact_id: 'unknown', local_path: '/tmp/other.md', operation: 'inspect' }) }),
    ], []);

    expect(result.produced.map((value) => value.artifactId)).toEqual(['created', 'modified', 'overwritten', 'appended']);
    expect(result.retrieved.map((value) => value.artifactId)).toEqual(['read']);
    expect(result.ungrouped.map((value) => value.artifactId)).toEqual(['unknown']);
    expect(result.all.map((value) => value.artifactId)).toEqual(['created', 'modified', 'overwritten', 'appended', 'read', 'unknown']);
  });

  it('keeps the finalizer artifact while adding timeline verification and provenance', () => {
    const result = deriveAgentTaskArtifacts([
      file({ artifact: artifact({ display_name: 'final-report.md', local_path: '/tmp/reports/../report.md' }) }),
    ], [entry({
      metadata: {
        artifact: artifact({
          display_name: 'timeline-report.md',
          local_path: '/tmp/report.md',
          lifecycle: 'verified',
          verification: { status: 'verified' },
        }),
      },
    })]);

    expect(result.all).toEqual([expect.objectContaining({
      displayName: 'final-report.md',
      lifecycle: 'verified',
      verification: { status: 'verified' },
      sourceTimelineEntryId: 'timeline-report',
      sourceStepId: 'step-write',
    })]);
  });

  it('merges failed timeline verification evidence into the finalizer artifact', () => {
    const result = deriveAgentTaskArtifacts([file()], [entry({
      metadata: {
        artifact: artifact({
          lifecycle: 'failed',
          verification: { status: 'failed', summary: 'Verification failed' },
        }),
      },
    })]);

    expect(result.all).toEqual([expect.objectContaining({
      lifecycle: 'failed',
      verification: { status: 'failed', summary: 'Verification failed' },
    })]);
  });

  it('deduplicates repeated same-path finalizer edits in first durable order', () => {
    const result = deriveAgentTaskArtifacts([
      file({ artifact: artifact({ artifact_id: 'first', local_path: '/tmp/report.md', operation: 'write' }) }),
      file({ artifact: artifact({ artifact_id: 'second', local_path: '/tmp/report.md', operation: 'update' }) }),
    ], []);

    expect(result.all.map((value) => value.artifactId)).toEqual(['first']);
  });

  it('deduplicates pathless artifacts by stable ID and preserves timeline-only artifacts', () => {
    const pathless = artifact({ artifact_id: 'artifact-pathless', local_path: null, lifecycle: 'unavailable', preview: { capability: 'unsupported' } });
    const result = deriveAgentTaskArtifacts([
      file({ artifact: pathless }),
      file({ artifact: pathless }),
    ], [entry({
      id: 'timeline-unicode',
      metadata: { artifact: artifact({ artifact_id: 'artifact-unicode', display_name: 'résumé-東京.md', local_path: '/tmp/résumé-東京.md' }) },
    })]);

    expect(result.all.map((value) => value.artifactId)).toEqual(['artifact-pathless', 'artifact-unicode']);
    expect(result.all[1].sourceTimelineEntryId).toBe('timeline-unicode');
  });

  it('ignores malformed selected artifacts and never reads raw metadata.file', () => {
    const result = deriveAgentTaskArtifacts([
      file({ path: '', artifact: { artifact_id: 'broken' } }),
    ], [entry({
      metadata: {
        artifact: { artifact_id: 'broken' },
        file: artifact({ artifact_id: 'raw-file', local_path: '/tmp/raw-file.md' }),
      },
    })]);

    expect(result).toEqual({ all: [], produced: [], retrieved: [], ungrouped: [] });
  });

  it('does not replace a finalizer artifact with non-evidentiary timeline metadata', () => {
    const result = deriveAgentTaskArtifacts([
      file({ artifact: artifact({ operation: 'write', verification: { status: 'unknown' } }) }),
    ], [entry({
      metadata: { artifact: artifact({ operation: 'read', verification: { status: 'pending' } }) },
    })]);

    expect(result.all).toEqual([expect.objectContaining({
      operation: 'write',
      group: 'produced',
      verification: { status: 'unknown' },
      sourceTimelineEntryId: 'timeline-report',
      sourceStepId: 'step-write',
    })]);
  });

  it('derives a previewable artifact from a final-result file before hydration', () => {
    const pdfPath = '/tmp/reports/../deliverable.pdf';
    const result = deriveAgentTaskArtifacts([
      {
        name: 'deliverable.pdf',
        path: pdfPath,
        operation: 'create',
      } as StructuredFile,
    ], []);

    expect(result.produced).toEqual([expect.objectContaining({
      artifactId: 'legacy:/tmp/deliverable.pdf',
      displayName: 'deliverable.pdf',
      localPath: '/tmp/deliverable.pdf',
      artifactKind: 'file',
      operation: 'create',
      lifecycle: 'ready',
      preview: { capability: 'unknown' },
      verification: { status: 'unknown' },
      group: 'produced',
    })]);
    expect(result.all).toHaveLength(1);

    const hydrated = deriveAgentTaskArtifacts([
      {
        name: 'deliverable.pdf',
        path: pdfPath,
        operation: 'create',
      } as StructuredFile,
    ], [entry({
      metadata: {
        artifact: artifact({
          artifact_id: 'artifact-deliverable',
          display_name: 'deliverable.pdf',
          local_path: '/tmp/deliverable.pdf',
          lifecycle: 'verified',
          verification: { status: 'verified' },
        }),
      },
    })]);

    expect(hydrated.all).toHaveLength(1);
    expect(hydrated.produced[0]).toEqual(expect.objectContaining({
      artifactId: 'legacy:/tmp/deliverable.pdf',
      lifecycle: 'verified',
      verification: { status: 'verified' },
      sourceTimelineEntryId: 'timeline-report',
    }));
  });

  it('carries a timeline-sourced review payload onto the merged artifact', () => {
    const finalizerFile: StructuredFile = {
      name: 'report.md',
      path: '/tmp/workspace/report.md',
      operation: 'create',
    };
    const timelineEntry = entry({
      id: 'artifact_file-0123456789abcdef01234567',
      type: 'artifact',
      metadata: {
        artifact: {
          artifact_id: 'file-0123456789abcdef01234567',
          display_name: 'report.md',
          local_path: '/tmp/workspace/report.md',
          artifact_kind: 'file',
          operation: 'create',
          lifecycle: 'verified',
          preview: { capability: 'unknown' },
          verification: { status: 'verified', summary: 'Verified 4 bytes; SHA-256 ' + 'a'.repeat(64) + '.' },
          review: { revision: 1, revision_count: 1, kind: 'markdown', snapshot_status: 'available' },
        },
      },
    });

    const derived = deriveAgentTaskArtifacts([finalizerFile], [timelineEntry]);

    expect(derived.all).toHaveLength(1);
    expect(derived.all[0].review).toEqual({
      revision: 1,
      revisionCount: 1,
      kind: 'markdown',
      snapshotStatus: 'available',
    });
  });
});
