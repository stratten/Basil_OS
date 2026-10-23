import { describe, expect, it } from 'vitest';
import { timelineEntryTime } from './timelineEntryTime';

describe('timelineEntryTime', () => {
  it('parses ISO timestamps', () => {
    expect(timelineEntryTime('2026-10-16T10:00:00.000Z')).toBe(Date.parse('2026-10-16T10:00:00.000Z'));
  });

  it('reads numeric epoch seconds, as numbers and as numeric strings', () => {
    expect(timelineEntryTime(1_760_608_800.5)).toBe(1_760_608_800_500);
    expect(timelineEntryTime('1760608800')).toBe(1_760_608_800_000);
  });

  it('keeps epoch milliseconds as they are', () => {
    expect(timelineEntryTime(1_760_608_800_000)).toBe(1_760_608_800_000);
  });

  it('returns NaN for empty, malformed, or non-scalar values', () => {
    expect(timelineEntryTime('')).toBeNaN();
    expect(timelineEntryTime('   ')).toBeNaN();
    expect(timelineEntryTime('not a date')).toBeNaN();
    expect(timelineEntryTime(undefined)).toBeNaN();
    expect(timelineEntryTime(null)).toBeNaN();
    expect(timelineEntryTime(Number.POSITIVE_INFINITY)).toBeNaN();
    expect(timelineEntryTime({})).toBeNaN();
  });
});
