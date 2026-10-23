import { describe, expect, it } from 'vitest';
import {
  ACTIVITY_TRAIL_LIMIT,
  activityStatusSnapshot,
  selectActivityTrail,
} from './activityPresentation';
import type { TimelineEntry } from '../../types';

const entry = (id: string, overrides: Partial<TimelineEntry> = {}): TimelineEntry => ({
  id,
  type: 'step',
  timestamp: '2026-07-13T12:00:00Z',
  content: id,
  ...overrides,
});

describe('selectActivityTrail', () => {
  it('returns the last N readable entries in chronological order', () => {
    const trail = selectActivityTrail([
      entry('first', { metadata: { progress_step: 'first' } }),
      entry('second', { metadata: { progress_step: 'second' } }),
      entry('third', { metadata: { progress_step: 'third' } }),
      entry('fourth', { metadata: { progress_step: 'fourth' } }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['second', 'third', 'fourth']);
    expect(ACTIVITY_TRAIL_LIMIT).toBe(3);
  });

  it('returns all entries when fewer than the limit', () => {
    const trail = selectActivityTrail([
      entry('only', { metadata: { progress_step: 'only' } }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['only']);
  });

  it('excludes thinking noise', () => {
    const trail = selectActivityTrail([
      entry('think', { type: 'thinking', content: 'reasoning...' }),
      entry('real', { metadata: { progress_step: 'real' } }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['real']);
  });

  it('excludes raw tool-detail payloads flagged raw_detail', () => {
    const trail = selectActivityTrail([
      entry('raw', {
        detail_kind: 'tool_result',
        content: 'Ran shell command',
        metadata: { raw_detail: true, progress_step: 'Ran shell command' },
      }),
      entry('progress', { metadata: { progress_step: 'Reading inbox' } }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['progress']);
  });

  it('includes historical entries that lack progress_step via type/detail_kind', () => {
    const trail = selectActivityTrail([
      entry('legacy-note', { detail_kind: 'step_note', content: 'Considering options', metadata: undefined }),
      entry('legacy-complete', { type: 'tool_complete', detail_kind: 'tool_result', content: 'Sent email', metadata: undefined }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['legacy-note', 'legacy-complete']);
  });

  it('drops entries whose readable text is empty', () => {
    const trail = selectActivityTrail([
      entry('empty', { content: '', summary: '' }),
      entry('kept', { metadata: { progress_step: 'Working' }, content: 'Working' }),
    ]);

    expect(trail.map(e => e.id)).toEqual(['kept']);
  });
});

describe('activityStatusSnapshot', () => {
  it('returns the readable text of the newest progress entry', () => {
    expect(activityStatusSnapshot([
      entry('one', { content: 'Planning approach', metadata: { progress_step: 'Planning approach' } }),
      entry('two', { content: 'Reading inbox', metadata: { progress_step: 'Reading inbox' } }),
    ])).toBe('Reading inbox');
  });

  it('returns undefined for an empty or no-progress timeline', () => {
    expect(activityStatusSnapshot([])).toBeUndefined();
    expect(activityStatusSnapshot([
      entry('think', { type: 'thinking', content: 'reasoning' }),
    ])).toBeUndefined();
  });
});
