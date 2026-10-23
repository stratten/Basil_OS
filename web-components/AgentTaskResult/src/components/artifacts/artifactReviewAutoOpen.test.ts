import { describe, expect, it } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import {
  isAutoOpenEligible,
  recordArtifactReviewFingerprints,
  selectArtifactForAutoOpen,
} from './artifactReviewAutoOpen';

function producedArtifact(overrides: Partial<DerivedAgentTaskArtifact> = {}): DerivedAgentTaskArtifact {
  return {
    artifactId: 'file-a',
    displayName: 'report.md',
    localPath: '/tmp/report.md',
    artifactKind: 'file',
    operation: 'create',
    lifecycle: 'verified',
    preview: { capability: 'unknown' },
    verification: { status: 'verified' },
    group: 'produced',
    review: { revision: 1, revisionCount: 1, kind: 'markdown', snapshotStatus: 'available' },
    ...overrides,
  };
}

describe('isAutoOpenEligible', () => {
  it('accepts a produced, previewable file artifact', () => {
    expect(isAutoOpenEligible(producedArtifact())).toBe(true);
  });

  it('rejects a retrieved artifact', () => {
    expect(isAutoOpenEligible(producedArtifact({ group: 'retrieved' }))).toBe(false);
  });

  it('rejects an artifact with no local path', () => {
    expect(isAutoOpenEligible(producedArtifact({ localPath: undefined }))).toBe(false);
  });

  it('rejects an artifact marked preview-unsupported', () => {
    expect(isAutoOpenEligible(producedArtifact({ preview: { capability: 'unsupported' } }))).toBe(false);
  });
});

describe('selectArtifactForAutoOpen', () => {
  it('records hydrated artifacts as the initial baseline without selecting them', () => {
    const seen = new Map<string, string>();

    recordArtifactReviewFingerprints([producedArtifact()], seen);

    expect(seen.get('file-a')).toBe('file-a:verified:1');
    expect(selectArtifactForAutoOpen([producedArtifact()], seen, new Map())).toBeUndefined();
  });

  it('selects a newly finalized produced artifact on first sight', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>();
    const selected = selectArtifactForAutoOpen([producedArtifact()], seen, dismissed);
    expect(selected).toBe('file-a');
  });

  it('does not re-select the same artifact at the same revision on a later call', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>();
    selectArtifactForAutoOpen([producedArtifact()], seen, dismissed);
    const secondCall = selectArtifactForAutoOpen([producedArtifact()], seen, dismissed);
    expect(secondCall).toBeUndefined();
  });

  it('re-selects the same artifact when its revision count increases', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>();
    selectArtifactForAutoOpen([producedArtifact()], seen, dismissed);
    const revised = producedArtifact({ review: { revision: 2, revisionCount: 2, kind: 'markdown', snapshotStatus: 'available' } });
    const selected = selectArtifactForAutoOpen([revised], seen, dismissed);
    expect(selected).toBe('file-a');
  });

  it('does not re-select an artifact whose current fingerprint was explicitly dismissed', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>([['file-a', 'file-a:verified:1']]);
    const selected = selectArtifactForAutoOpen([producedArtifact()], seen, dismissed);
    expect(selected).toBeUndefined();
  });

  it('re-selects after dismissal once a new revision arrives', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>([['file-a', 'file-a:verified:1']]);
    const revised = producedArtifact({ review: { revision: 2, revisionCount: 2, kind: 'markdown', snapshotStatus: 'available' } });
    const selected = selectArtifactForAutoOpen([revised], seen, dismissed);
    expect(selected).toBe('file-a');
  });

  it('selects the first eligible artifact when several are newly finalized in the same turn', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>();
    const first = producedArtifact({ artifactId: 'file-a' });
    const second = producedArtifact({ artifactId: 'file-b', displayName: 'summary.md', localPath: '/tmp/summary.md' });
    const selected = selectArtifactForAutoOpen([first, second], seen, dismissed);
    expect(selected).toBe('file-a');
  });

  it('ignores retrieved artifacts entirely', () => {
    const seen = new Map<string, string>();
    const dismissed = new Map<string, string>();
    const selected = selectArtifactForAutoOpen([producedArtifact({ group: 'retrieved' })], seen, dismissed);
    expect(selected).toBeUndefined();
  });
});
