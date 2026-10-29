import { describe, expect, it } from 'vitest';
import {
  LINK_NEAREST_MAX_SECONDS,
  LINK_TOLERANCE_SECONDS,
  anchorRowId,
  chipsByRow,
  spanRowIds,
  timedRowFromLine,
  type TimedTranscriptRow,
} from './companionTranscriptLinks';
import type { TranscriptLineDTO } from '../bridge/types';
import type { CompanionItem } from './types';

/** A meeting as the Notetaker draws it: microphone and system-audio lines interleaved on one timeline, the way the recorder's segments (and so the Companion's turns) are timed. */
const rows: TimedTranscriptRow[] = [
  { id: 'l1', start: 0, end: 4.2 },
  { id: 'l2', start: 4.4, end: 9 },
  { id: 'l3', start: 8.5, end: 14 },
  { id: 'l4', start: 14.2, end: 20 },
  { id: 'l5', start: 21, end: 30 },
  { id: 'untimed', start: null, end: null },
  { id: 'l6', start: 90, end: 97 },
];

function item(id: string, seq: number, start: number, end: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id, seq, kind: 'insight', text: id, confidence: 0.5, citations: [], no_source: false,
    transcript_range: { start, end, turn_ids: [] }, trigger: 'periodic', watch_id: null,
    truncated: false, pinned: false, dismissed: false, ...overrides,
  };
}

describe('spanRowIds', () => {
  it('returns every line that overlaps the range, in transcript order, including interleaved sources', () => {
    expect(spanRowIds(rows, { start: 5, end: 15 })).toEqual(['l2', 'l3', 'l4']);
  });

  it('matches a range that is exactly one line', () => {
    expect(spanRowIds(rows, { start: 21, end: 30 })).toEqual(['l5']);
  });

  it('absorbs small drift at the edges with the tolerance and no more', () => {
    expect(spanRowIds(rows, { start: 20.2, end: 20.2 })).toEqual(['l4']);
    expect(spanRowIds(rows, { start: 4.3, end: 4.3 })).toEqual(['l1', 'l2']);
    expect(LINK_TOLERANCE_SECONDS).toBeLessThan(1);
  });

  it('handles a zero-length range', () => {
    expect(spanRowIds(rows, { start: 9, end: 9 })).toEqual(['l2', 'l3']);
  });

  it('uses the nearest line when nothing overlaps and it is close enough', () => {
    expect(spanRowIds(rows, { start: 60, end: 60 })).toEqual([]);
    expect(spanRowIds(rows, { start: 40, end: 40 })).toEqual(['l5']);
    expect(spanRowIds(rows, { start: 82, end: 82 })).toEqual(['l6']);
  });

  it('links to nothing rather than to something unrelated', () => {
    expect(spanRowIds(rows, { start: 5000, end: 5010 })).toEqual([]);
    expect(LINK_NEAREST_MAX_SECONDS).toBeGreaterThan(0);
  });

  it('never matches lines without timeline seconds, and copes with an empty transcript', () => {
    expect(spanRowIds([{ id: 'x', start: null, end: null }], { start: 0, end: 10 })).toEqual([]);
    expect(spanRowIds([], { start: 0, end: 10 })).toEqual([]);
  });

  it('treats a line with a start but no end as a single instant', () => {
    expect(spanRowIds([{ id: 'x', start: 12, end: null }], { start: 11.5, end: 12.5 })).toEqual(['x']);
  });
});

describe('anchorRowId and chipsByRow', () => {
  it('anchors a chip on the last line of the span', () => {
    expect(anchorRowId(rows, { start: 5, end: 15 })).toBe('l4');
    expect(anchorRowId(rows, { start: 5000, end: 5001 })).toBeNull();
  });

  it('groups several items on one line in arrival order and skips dismissed and unmappable items', () => {
    const chips = chipsByRow(rows, [
      item('late', 9, 15, 19),
      item('early', 3, 16, 19.5),
      item('gone', 4, 16, 19, { dismissed: true }),
      item('lost', 5, 9000, 9001),
      item('other', 6, 0, 3),
    ]);
    expect(chips.get('l4')).toEqual(['early', 'late']);
    expect(chips.get('l1')).toEqual(['other']);
    expect(chips.size).toBe(2);
  });
});

describe('timedRowFromLine', () => {
  it('reads the same timeline seconds the transcript shows', () => {
    const line = { id: 'a', timelineStartSeconds: 3, timelineEndSeconds: 5 } as TranscriptLineDTO;
    expect(timedRowFromLine(line)).toEqual({ id: 'a', start: 3, end: 5 });
    expect(timedRowFromLine({ ...line, timelineEndSeconds: null })).toEqual({ id: 'a', start: 3, end: 3 });
  });
});
