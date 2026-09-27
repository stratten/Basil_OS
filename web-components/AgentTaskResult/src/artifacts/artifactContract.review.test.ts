import { describe, expect, it } from 'vitest';
import { parseAgentTaskArtifact } from './artifactContract';

function baseArtifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: 'file-0123456789abcdef01234567',
    display_name: 'report.md',
    local_path: '/tmp/report.md',
    artifact_kind: 'file',
    operation: 'create',
    lifecycle: 'verified',
    preview: { capability: 'unknown' },
    verification: { status: 'verified', summary: 'Verified 4 bytes; SHA-256 ' + 'a'.repeat(64) + '.' },
    ...overrides,
  };
}

describe('parseAgentTaskArtifact review metadata', () => {
  it('parses an available review payload', () => {
    const parsed = parseAgentTaskArtifact(
      baseArtifact({ review: { revision: 1, revision_count: 1, kind: 'markdown', snapshot_status: 'available' } }),
    );
    expect(parsed?.review).toEqual({ revision: 1, revisionCount: 1, kind: 'markdown', snapshotStatus: 'available' });
  });

  it('parses an unavailable review payload with a reason', () => {
    const parsed = parseAgentTaskArtifact(
      baseArtifact({
        review: {
          revision: null,
          revision_count: 0,
          snapshot_status: 'unavailable',
          unavailable_reason: 'Snapshot unavailable: unsupported file type.',
        },
      }),
    );
    expect(parsed?.review).toEqual({
      revision: null,
      revisionCount: 0,
      snapshotStatus: 'unavailable',
      unavailableReason: 'Snapshot unavailable: unsupported file type.',
    });
  });

  it('omits review entirely when the field is absent', () => {
    const parsed = parseAgentTaskArtifact(baseArtifact());
    expect(parsed).toBeDefined();
    expect(parsed?.review).toBeUndefined();
  });

  it('omits review entirely when the field is null', () => {
    const parsed = parseAgentTaskArtifact(baseArtifact({ review: null }));
    expect(parsed).toBeDefined();
    expect(parsed?.review).toBeUndefined();
  });

  it('rejects the whole artifact when review has an invalid snapshot_status', () => {
    const parsed = parseAgentTaskArtifact(
      baseArtifact({ review: { revision: 1, revision_count: 1, snapshot_status: 'bogus' } }),
    );
    expect(parsed).toBeUndefined();
  });

  it('rejects the whole artifact when review.revision is zero', () => {
    const parsed = parseAgentTaskArtifact(
      baseArtifact({ review: { revision: 0, revision_count: 1, snapshot_status: 'available', kind: 'markdown' } }),
    );
    expect(parsed).toBeUndefined();
  });

  it('rejects an unavailable_reason longer than 160 characters', () => {
    const parsed = parseAgentTaskArtifact(
      baseArtifact({
        review: {
          revision: null,
          revision_count: 0,
          snapshot_status: 'unavailable',
          unavailable_reason: 'x'.repeat(161),
        },
      }),
    );
    expect(parsed).toBeUndefined();
  });
});
