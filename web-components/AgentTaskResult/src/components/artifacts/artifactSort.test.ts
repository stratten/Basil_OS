import { describe, expect, it } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import { nextArtifactSort, sortArtifacts } from './artifactSort';

function make(displayName: string, lastTouchedAt?: string): DerivedAgentTaskArtifact {
  return {
    artifactId: displayName,
    displayName,
    artifactKind: 'file',
    lifecycle: 'ready',
    preview: { capability: 'unknown' },
    verification: { status: 'unknown' },
    group: 'produced',
    ...(lastTouchedAt ? { lastTouchedAt } : {}),
  };
}

const names = (artifacts: DerivedAgentTaskArtifact[]) => artifacts.map(artifact => artifact.displayName);

describe('sortArtifacts', () => {
  const files = [
    make('b-10.md', '2026-08-09T20:00:00Z'),
    make('a.sh', '2026-08-09T22:00:00Z'),
    make('b-2.md', '2026-08-09T21:00:00Z'),
    make('notes.txt'),
    make('Z.py', '2026-08-09T19:00:00Z'),
  ];

  it('keeps the run order, without mutating the input, when there is no sort', () => {
    const copy = [...files];
    expect(names(sortArtifacts(files, null))).toEqual(names(files));
    expect(files).toEqual(copy);
  });

  it('sorts by name, case-insensitively and numerically', () => {
    expect(names(sortArtifacts(files, { key: 'name', direction: 'asc' }))).toEqual([
      'a.sh', 'b-2.md', 'b-10.md', 'notes.txt', 'Z.py',
    ]);
    expect(names(sortArtifacts(files, { key: 'name', direction: 'desc' }))).toEqual([
      'Z.py', 'notes.txt', 'b-10.md', 'b-2.md', 'a.sh',
    ]);
  });

  it('sorts by modified time and keeps files with no time last in either direction', () => {
    expect(names(sortArtifacts(files, { key: 'modified', direction: 'desc' }))).toEqual([
      'a.sh', 'b-2.md', 'b-10.md', 'Z.py', 'notes.txt',
    ]);
    expect(names(sortArtifacts(files, { key: 'modified', direction: 'asc' }))).toEqual([
      'Z.py', 'b-10.md', 'b-2.md', 'a.sh', 'notes.txt',
    ]);
  });

  it('groups by type, then by name', () => {
    expect(names(sortArtifacts(files, { key: 'type', direction: 'asc' }))).toEqual([
      'b-2.md', 'b-10.md', 'Z.py', 'a.sh', 'notes.txt',
    ]);
  });

  it('keeps the original order for ties', () => {
    const tied = [make('x.md', '2026-08-09T20:00:00Z'), make('y.md', '2026-08-09T20:00:00Z')];
    expect(names(sortArtifacts(tied, { key: 'modified', direction: 'desc' }))).toEqual(['x.md', 'y.md']);
  });
});

describe('nextArtifactSort', () => {
  it('starts a key in its natural direction, reverses it, then returns to run order', () => {
    const first = nextArtifactSort(null, 'name');
    expect(first).toEqual({ key: 'name', direction: 'asc' });
    const second = nextArtifactSort(first, 'name');
    expect(second).toEqual({ key: 'name', direction: 'desc' });
    expect(nextArtifactSort(second, 'name')).toBeNull();
  });

  it('uses newest-first as the natural direction for modified', () => {
    expect(nextArtifactSort(null, 'modified')).toEqual({ key: 'modified', direction: 'desc' });
  });

  it('restarts when switching to a different key', () => {
    expect(nextArtifactSort({ key: 'name', direction: 'desc' }, 'type')).toEqual({ key: 'type', direction: 'asc' });
  });
});
