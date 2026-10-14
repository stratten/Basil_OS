import { describe, expect, it } from 'vitest';
import { LATENCY_MIN_SAMPLES, LATENCY_SAMPLE_WINDOW, companionLatencySummary, formatLatencySummary } from './companionLatency';
import type { CompanionItem } from './types';

function item(id: string, latency?: number | null): CompanionItem {
  return {
    id,
    kind: 'insight',
    text: `text ${id}`,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: 0, end: 2, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...(latency === undefined ? {} : { latency_ms: latency }),
  };
}

describe('companionLatencySummary', () => {
  it('needs the minimum number of stamped items and ignores unstamped, null and invalid ones', () => {
    expect(LATENCY_MIN_SAMPLES).toBe(3);
    expect(companionLatencySummary([])).toBeNull();
    expect(companionLatencySummary([item('a', 1000), item('b', 2000)])).toBeNull();
    expect(companionLatencySummary([item('a', 1000), item('b', 2000), item('c'), item('d', null), item('e', -5), item('f', Number.NaN)])).toBeNull();
  });

  it('computes the median and the slow value with nearest rank, regardless of input order', () => {
    const summary = companionLatencySummary([item('a', 3000), item('b', 1000), item('c', 2000)]);
    expect(summary).toEqual({ medianSeconds: 2, slowSeconds: 3, sampleCount: 3 });
    expect(formatLatencySummary(summary!)).toBe('Replies in about 2.0s, slow ones 3.0s');
  });

  it('uses only the most recent window and rounds values of ten seconds or more', () => {
    expect(LATENCY_SAMPLE_WINDOW).toBe(20);
    const old = Array.from({ length: 5 }, (_, index) => item(`old${index}`, 60000));
    const recent = Array.from({ length: 20 }, (_, index) => item(`new${index}`, (index + 1) * 1000));
    const summary = companionLatencySummary([...old, ...recent]);
    expect(summary).toEqual({ medianSeconds: 10, slowSeconds: 19, sampleCount: 20 });
    expect(formatLatencySummary(summary!)).toBe('Replies in about 10s, slow ones 19s');
  });
});
