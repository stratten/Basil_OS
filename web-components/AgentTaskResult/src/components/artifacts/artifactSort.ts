import { parseTouchedAt, type DerivedAgentTaskArtifact } from './artifactDerivation';
import { classifyArtifactFileType } from './artifactFileType';

export type ArtifactSortKey = 'name' | 'modified' | 'type';
export type ArtifactSortDirection = 'asc' | 'desc';

/** `null` is the run's own order (the order the agent produced the files in). */
export interface ArtifactSort {
  key: ArtifactSortKey;
  direction: ArtifactSortDirection;
}
export type ArtifactSortState = ArtifactSort | null;

export const ARTIFACT_SORT_KEYS: readonly ArtifactSortKey[] = ['name', 'modified', 'type'];

const DEFAULT_DIRECTIONS: Record<ArtifactSortKey, ArtifactSortDirection> = {
  name: 'asc',
  modified: 'desc',
  type: 'asc',
};

const nameCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/**
 * One click on a key sorts by it in its natural direction, a second click reverses it, and a third returns to the run's own order. Clicking a different key starts that key over.
 */
export function nextArtifactSort(current: ArtifactSortState, key: ArtifactSortKey): ArtifactSortState {
  if (!current || current.key !== key) return { key, direction: DEFAULT_DIRECTIONS[key] };
  if (current.direction === DEFAULT_DIRECTIONS[key]) {
    return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' };
  }
  return null;
}

/**
 * Returns a new, sorted array; the input is never mutated. Ties and missing values keep the run's original order, so the result is deterministic. Files with no recorded modified time sort after the others in either direction.
 */
export function sortArtifacts(
  artifacts: readonly DerivedAgentTaskArtifact[],
  sort: ArtifactSortState,
): DerivedAgentTaskArtifact[] {
  const indexed = artifacts.map((artifact, index) => ({ artifact, index }));
  if (!sort) return indexed.map(({ artifact }) => artifact);

  const sign = sort.direction === 'asc' ? 1 : -1;
  indexed.sort((a, b) => {
    if (sort.key === 'modified') {
      const aMs = parseTouchedAt(a.artifact.lastTouchedAt);
      const bMs = parseTouchedAt(b.artifact.lastTouchedAt);
      if (aMs === undefined && bMs === undefined) return a.index - b.index;
      if (aMs === undefined) return 1;
      if (bMs === undefined) return -1;
      if (aMs !== bMs) return (aMs - bMs) * sign;
      return a.index - b.index;
    }
    if (sort.key === 'type') {
      const typeDelta = classifyArtifactFileType(a.artifact).sortRank - classifyArtifactFileType(b.artifact).sortRank;
      if (typeDelta !== 0) return typeDelta * sign;
      const nameDelta = nameCollator.compare(a.artifact.displayName, b.artifact.displayName);
      return nameDelta !== 0 ? nameDelta : a.index - b.index;
    }
    const nameDelta = nameCollator.compare(a.artifact.displayName, b.artifact.displayName);
    return nameDelta !== 0 ? nameDelta * sign : a.index - b.index;
  });
  return indexed.map(({ artifact }) => artifact);
}
