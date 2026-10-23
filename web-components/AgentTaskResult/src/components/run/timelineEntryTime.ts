const EPOCH_SECONDS_CEILING = 1e11;
const NUMERIC_TIMESTAMP = /^\d+(?:\.\d+)?$/;

/** Milliseconds since the epoch for a timeline timestamp, or NaN when it cannot be read. Accepts ISO strings and the numeric epoch seconds that older approval activity entries were stored with. */
export function timelineEntryTime(value: unknown): number {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return Number.NaN;
    return value < EPOCH_SECONDS_CEILING ? value * 1000 : value;
  }
  if (typeof value !== 'string') return Number.NaN;
  const trimmed = value.trim();
  if (!trimmed) return Number.NaN;
  if (NUMERIC_TIMESTAMP.test(trimmed)) return timelineEntryTime(Number(trimmed));
  return Date.parse(trimmed);
}
