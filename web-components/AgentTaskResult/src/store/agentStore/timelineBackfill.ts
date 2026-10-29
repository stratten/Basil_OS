import type { TimelineEntry } from '../../types';

// Live progress entries and the durable copies the backend persists are separate records with different ids, so a durable entry counts as already shown when a local entry carries the same text at nearly the same moment.
const SAME_EVENT_WINDOW_MS = 3_000;

/** Parses a backend timestamp, trimming fractional seconds to milliseconds because not every WebKit build accepts microseconds. */
export function timelineTimestampMs(timestamp: string | undefined): number | undefined {
  if (!timestamp) return undefined;
  const trimmed = timestamp.replace(/(\.\d{3})\d+/, '$1');
  const parsed = Date.parse(trimmed);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function normalizedContent(entry: TimelineEntry): string {
  return (entry.content || entry.summary || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function isAlreadyShown(local: TimelineEntry[], durable: TimelineEntry, durableAtMs: number): boolean {
  const durableContent = normalizedContent(durable);
  return local.some(entry => {
    if (entry.id && entry.id === durable.id) return true;
    if (normalizedContent(entry) !== durableContent) return false;
    const localAtMs = timelineTimestampMs(entry.timestamp);
    return localAtMs !== undefined && Math.abs(localAtMs - durableAtMs) <= SAME_EVENT_WINDOW_MS;
  });
}

/**
 * Adds durable timeline entries that the live feed never delivered.
 *
 * Only entries at or after `sinceMs` (less the same-event window) are considered, so a task whose feed was never interrupted is left exactly as it is. Artifact entries are skipped because their own reconciliation owns them. Added entries are placed by timestamp among the local ones; the original array is returned untouched when nothing was added.
 */
export function backfillDurableTimelineEntries(
  local: TimelineEntry[],
  durable: TimelineEntry[],
  sinceMs: number,
): TimelineEntry[] {
  const missing = durable
    .filter(entry => entry.type !== 'artifact' && normalizedContent(entry) !== '')
    .map(entry => ({ entry, atMs: timelineTimestampMs(entry.timestamp) }))
    .filter((item): item is { entry: TimelineEntry; atMs: number } => (
      item.atMs !== undefined && item.atMs >= sinceMs - SAME_EVENT_WINDOW_MS
    ))
    .filter(item => !isAlreadyShown(local, item.entry, item.atMs))
    .sort((a, b) => a.atMs - b.atMs);
  if (missing.length === 0) return local;

  const merged = [...local];
  for (const { entry, atMs } of missing) {
    const insertAt = merged.findIndex(existing => {
      const existingAtMs = timelineTimestampMs(existing.timestamp);
      return existingAtMs !== undefined && existingAtMs > atMs;
    });
    if (insertAt === -1) merged.push(entry);
    else merged.splice(insertAt, 0, entry);
  }
  return merged;
}
