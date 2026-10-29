import { describe, expect, it } from 'vitest';
import type { TimelineEntry } from '../../types';
import { backfillDurableTimelineEntries, timelineTimestampMs } from './timelineBackfill';

function entry(id: string, content: string, timestamp: string, type: TimelineEntry['type'] = 'step'): TimelineEntry {
  return { id, type, content, timestamp };
}

const T0 = Date.parse('2026-10-27T15:00:00.000Z');
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString();

describe('timelineTimestampMs', () => {
  it('parses microsecond timestamps and offsets', () => {
    expect(timelineTimestampMs('2026-10-27T15:00:29.234294+00:00')).toBe(Date.parse('2026-10-27T15:00:29.234Z'));
  });

  it('returns undefined for missing or malformed values', () => {
    expect(timelineTimestampMs(undefined)).toBeUndefined();
    expect(timelineTimestampMs('not a time')).toBeUndefined();
  });
});

describe('backfillDurableTimelineEntries', () => {
  it('adds durable entries from after the gap and orders them among the local ones', () => {
    const local = [entry('l1', 'Planning', at(0)), entry('l2', 'Finished', at(60))];
    const durable = [
      entry('d1', 'Planning', at(0.2)),
      entry('d2', 'Ran a command', at(20)),
      entry('d3', 'Read the output', at(30)),
      entry('d4', 'Finished', at(60.1)),
    ];

    const merged = backfillDurableTimelineEntries(local, durable, T0 + 10_000);

    expect(merged.map(item => item.content)).toEqual(['Planning', 'Ran a command', 'Read the output', 'Finished']);
  });

  it('does not re-add an event the live feed already delivered under a different id', () => {
    const local = [entry('live-1', 'Using shell', at(10))];
    const durable = [entry('durable-9', 'Using shell', at(10.05))];

    expect(backfillDurableTimelineEntries(local, durable, T0)).toBe(local);
  });

  it('ignores durable entries that predate the gap so an uninterrupted task is left alone', () => {
    const local = [entry('l1', 'Newest live step', at(100))];
    const durable = [entry('d1', 'Older step with different wording', at(5))];

    expect(backfillDurableTimelineEntries(local, durable, T0 + 90_000)).toBe(local);
  });

  it('adopts every durable entry when nothing is shown locally and the cutoff is zero', () => {
    const durable = [entry('d1', 'First', at(0)), entry('d2', 'Second', at(5))];

    const merged = backfillDurableTimelineEntries([], durable, 0);

    expect(merged.map(item => item.id)).toEqual(['d1', 'd2']);
  });

  it('keeps repeated identical steps that are far apart in time', () => {
    const local = [entry('l1', 'Analyzing results', at(10))];
    const durable = [entry('d2', 'Analyzing results', at(40))];

    const merged = backfillDurableTimelineEntries(local, durable, T0);

    expect(merged.map(item => item.id)).toEqual(['l1', 'd2']);
  });

  it('skips artifact entries and entries with no readable text', () => {
    const durable = [
      entry('a1', 'Wrote report.md', at(20), 'artifact'),
      entry('blank', '   ', at(21)),
    ];

    expect(backfillDurableTimelineEntries([], durable, 0)).toEqual([]);
  });

  it('returns the original array when the durable list is empty', () => {
    const local = [entry('l1', 'Only step', at(0))];

    expect(backfillDurableTimelineEntries(local, [], 0)).toBe(local);
  });

  it('does not mutate its inputs', () => {
    const local = [entry('l1', 'Start', at(0)), entry('l2', 'End', at(60))];
    const durable = [entry('d1', 'Middle', at(30))];
    const localSnapshot = JSON.stringify(local);

    backfillDurableTimelineEntries(local, durable, 0);

    expect(JSON.stringify(local)).toBe(localSnapshot);
  });
});
