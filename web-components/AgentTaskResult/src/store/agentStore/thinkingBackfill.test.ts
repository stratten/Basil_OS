import { describe, expect, it } from 'vitest';
import type { ThinkingSegment } from '../../types';
import { mergeEarlierThinkingSegments } from './thinkingBackfill';

const segment = (iteration: number, text: string): ThinkingSegment => ({ iteration, text, isComplete: true });

describe('mergeEarlierThinkingSegments', () => {
  it('puts persisted segments that come before the first local one in front of it', () => {
    const local = [segment(4, 'Streaming now')];
    const persisted = [segment(3, 'Third'), segment(1, 'First'), segment(2, 'Second'), segment(4, 'Persisted copy of four')];

    const merged = mergeEarlierThinkingSegments(local, persisted);

    expect(merged.map(item => item.text)).toEqual(['First', 'Second', 'Third', 'Streaming now']);
  });

  it('uses the persisted segments as they are when the window holds none', () => {
    const persisted = [segment(1, 'First')];
    expect(mergeEarlierThinkingSegments([], persisted)).toBe(persisted);
  });

  it('returns the local array untouched when nothing is persisted or nothing is earlier', () => {
    const local = [segment(2, 'Local')];
    expect(mergeEarlierThinkingSegments(local, [])).toBe(local);
    expect(mergeEarlierThinkingSegments(local, [segment(2, 'Same'), segment(5, 'Later')])).toBe(local);
  });
});
