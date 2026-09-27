import { describe, expect, it } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import {
  canOpenLocalServerPreview,
  canOpenStaticLocalWebPreview,
  canProbeLiveArtifactPreview,
  canReviewManagedHistoryArtifact,
  hasStoredArtifactRevision,
  selectArtifactsForPreview,
} from './artifactPreviewEligibility';

function artifact(overrides: Partial<DerivedAgentTaskArtifact> = {}): DerivedAgentTaskArtifact {
  return {
    artifactId: 'report',
    displayName: 'report.md',
    localPath: '/private/report.md',
    artifactKind: 'file',
    operation: 'create',
    lifecycle: 'ready',
    preview: { capability: 'unknown' },
    verification: { status: 'unknown' },
    group: 'produced',
    ...overrides,
  };
}

describe('artifact preview eligibility', () => {
  it('admits only host-confirmed live paths into preview-only surfaces', () => {
    const present = artifact();
    const missing = artifact({ artifactId: 'missing', localPath: '/private/missing.md' });

    expect(selectArtifactsForPreview([present, missing], new Set(['/private/report.md']))).toEqual([present]);
  });

  it('retains a durable revision even after its local path is unavailable', () => {
    const snapshot = artifact({
      artifactId: 'snapshot',
      lifecycle: 'unavailable',
      localPath: undefined,
      preview: { capability: 'unsupported' },
      review: {
        revision: 2,
        revisionCount: 2,
        kind: 'markdown',
        snapshotStatus: 'available',
      },
    });

    expect(hasStoredArtifactRevision(snapshot)).toBe(true);
    expect(canProbeLiveArtifactPreview(snapshot)).toBe(false);
    expect(selectArtifactsForPreview([snapshot], new Set())).toEqual([snapshot]);
  });

  it('retains a text artifact with an unavailable task snapshot so managed history can supply its durable version', () => {
    const managedHistoryCandidate = artifact({
      lifecycle: 'unavailable',
      preview: { capability: 'unsupported' },
      review: {
        revision: null,
        revisionCount: 0,
        kind: 'markdown',
        snapshotStatus: 'unavailable',
        unavailableReason: 'No task-owned snapshot exists for this follow-up.',
      },
    });

    expect(hasStoredArtifactRevision(managedHistoryCandidate)).toBe(false);
    expect(canProbeLiveArtifactPreview(managedHistoryCandidate)).toBe(false);
    expect(canReviewManagedHistoryArtifact(managedHistoryCandidate)).toBe(true);
    expect(selectArtifactsForPreview([managedHistoryCandidate], new Set())).toEqual([managedHistoryCandidate]);
  });

  it('permits the static preview action only for local HTML documents', () => {
    expect(canOpenStaticLocalWebPreview(artifact({ localPath: '/private/report.html' }))).toBe(true);
    expect(canOpenStaticLocalWebPreview(artifact({ localPath: '/private/report.HTM' }))).toBe(true);
    expect(canOpenStaticLocalWebPreview(artifact({ localPath: '/private/report.md' }))).toBe(false);
    expect(canOpenStaticLocalWebPreview(artifact({ localPath: '/private/report.txt' }))).toBe(false);
    expect(canOpenStaticLocalWebPreview(artifact({ localPath: '/private/report.py' }))).toBe(false);
  });

  it('permits the local-server preview action only for available local HTML documents', () => {
    expect(canOpenLocalServerPreview(artifact({ localPath: '/private/report.html' }))).toBe(true);
    expect(canOpenLocalServerPreview(artifact({ localPath: '/private/report.HTM' }))).toBe(true);
    expect(canOpenLocalServerPreview(artifact({ localPath: '/private/report.json' }))).toBe(false);
    expect(canOpenLocalServerPreview(artifact({ localPath: '/private/report.md' }))).toBe(false);
    expect(canOpenLocalServerPreview(artifact({ localPath: '/private/report.py' }))).toBe(false);
    expect(canOpenLocalServerPreview(artifact({ artifactKind: 'directory', localPath: '/private/reports' }))).toBe(false);
    expect(canOpenLocalServerPreview(artifact({ lifecycle: 'unavailable' }))).toBe(false);
    expect(canOpenLocalServerPreview(artifact({ localPath: undefined }))).toBe(false);
  });
});
