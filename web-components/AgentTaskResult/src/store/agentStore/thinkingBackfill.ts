import type { ThinkingSegment } from '../../types';

/**
 * Prepends the persisted reasoning segments that come before anything this window holds.
 *
 * A window opened mid-run only ever receives reasoning from that moment on, so persisted segments with a lower iteration than the lowest local one are the history it missed. A local segment is never replaced or reordered. The original array is returned untouched when nothing was added, and when the window holds no segments the persisted ones are returned as they are.
 */
export function mergeEarlierThinkingSegments(
  local: ThinkingSegment[],
  persisted: ThinkingSegment[],
): ThinkingSegment[] {
  if (persisted.length === 0) return local;
  if (local.length === 0) return persisted;
  const lowestLocalIteration = Math.min(...local.map(segment => segment.iteration));
  const earlier = persisted
    .filter(segment => segment.iteration < lowestLocalIteration)
    .sort((a, b) => a.iteration - b.iteration);
  return earlier.length === 0 ? local : [...earlier, ...local];
}
