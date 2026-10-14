import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  MAX_DERIVED_RETRIEVALS,
  applyTimelineEvent,
  emptyTimelineState,
  reduceTimeline,
  selectFeedItems,
  timelineStateFromSnapshot,
} from './companionReducer';
import { EMPTY_COMPANION_STATUS, type CompanionItem, type CompanionSnapshot, type TimelineEvent } from './types';

const FIXTURE_PATH = resolve(
  import.meta.dirname,
  '../../../../backend/src/tests/services/meeting_companion_tests/fixtures/timeline_parity.json',
);

interface ParityFixture {
  events: TimelineEvent[];
  expected: {
    items: Array<{ id: string; text: string; pinned: boolean; dismissed: boolean; watch_id: string | null }>;
    watches: Array<{ id: string; active: boolean; last_triggered_at: number | null }>;
    root_ids: string[];
    chat: Array<{ id: string; role: string; text: string; status: string; truncated: boolean }>;
    retrieval_count: number;
    status: Record<string, unknown> | null;
    last_error: { code: string; message: string } | null;
    last_seq: number;
  };
}

function loadFixture(): ParityFixture {
  return JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as ParityFixture;
}

function makeItem(id: string, end: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id,
    kind: 'insight',
    text: `text ${id}`,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: end - 2, end, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...overrides,
  };
}

function event(seq: number, kind: TimelineEvent['kind'], payload: Record<string, unknown>, meetingTime = seq): TimelineEvent {
  return { id: `e${seq}`, seq, kind, meeting_time: meetingTime, wall_time: '2026-01-01T00:00:00.000000Z', payload };
}

describe('companion reducer parity with the Python reduce_timeline', () => {
  it('derives the same state as the shared fixture expects', () => {
    const fixture = loadFixture();
    const state = reduceTimeline(fixture.events);
    expect(state.items.map((item) => ({ id: item.id, text: item.text, pinned: item.pinned, dismissed: item.dismissed, watch_id: item.watch_id }))).toEqual(fixture.expected.items);
    expect(state.watches.map((watch) => ({ id: watch.id, active: watch.active, last_triggered_at: watch.last_triggered_at }))).toEqual(fixture.expected.watches);
    expect(state.roots.map((root) => root.id)).toEqual(fixture.expected.root_ids);
    expect(state.chat.map((message) => ({ id: message.id, role: message.role, text: message.text, status: message.status, truncated: message.truncated }))).toEqual(fixture.expected.chat);
    expect(state.retrievals).toHaveLength(fixture.expected.retrieval_count);
    expect(state.statusEvent).toEqual(fixture.expected.status);
    expect(state.lastError).toEqual(fixture.expected.last_error);
    expect(state.lastSeq).toBe(fixture.expected.last_seq);
  });

  it('keeps the fixture at the documented size so a silent truncation is noticed', () => {
    expect(loadFixture().events).toHaveLength(18);
  });
});

describe('companion reducer edge cases', () => {
  it('skips a malformed item but still advances lastSeq', () => {
    const state = applyTimelineEvent(emptyTimelineState, event(7, 'item', {}));
    expect(state.items).toEqual([]);
    expect(state.lastSeq).toBe(7);
  });

  it('never replaces an existing item with a later event for the same id', () => {
    const first = event(1, 'item', { item: makeItem('i1', 10) });
    const second = event(2, 'item', { item: makeItem('i1', 20, { text: 'changed' }) });
    const state = reduceTimeline([first, second]);
    expect(state.items).toHaveLength(1);
    expect(state.items[0].text).toBe('text i1');
  });

  it('lets a pin restore a dismissed item and a dismissal clear a pin', () => {
    const state = reduceTimeline([
      event(1, 'item', { item: makeItem('i1', 10) }),
      event(2, 'feedback', { item_id: 'i1', action: 'dismissed' }),
      event(3, 'feedback', { item_id: 'i1', action: 'pinned' }),
    ]);
    expect(state.items[0]).toMatchObject({ pinned: true, dismissed: false });
    const dismissedAgain = applyTimelineEvent(state, event(4, 'feedback', { item_id: 'i1', action: 'dismissed' }));
    expect(dismissedAgain.items[0]).toMatchObject({ pinned: false, dismissed: true });
  });

  it('ignores feedback actions that do not change the feed', () => {
    const seeded = reduceTimeline([event(1, 'item', { item: makeItem('i1', 10) })]);
    const state = applyTimelineEvent(seeded, event(2, 'feedback', { item_id: 'i1', action: 'copied' }));
    expect(state.items).toEqual(seeded.items);
    expect(state.lastSeq).toBe(2);
  });

  it('records the latest error event', () => {
    const state = reduceTimeline([event(1, 'error', { code: 'model_failed', message: 'The model call failed.' })]);
    expect(state.lastError).toEqual({ code: 'model_failed', message: 'The model call failed.' });
  });

  it('caps retained retrievals at the Python limit and keeps the newest', () => {
    const events = Array.from({ length: MAX_DERIVED_RETRIEVALS + 5 }, (_, index) => event(index + 1, 'retrieval', { purpose: 'prefetch' }));
    const state = reduceTimeline(events);
    expect(state.retrievals).toHaveLength(MAX_DERIVED_RETRIEVALS);
    expect(state.retrievals[0].seq).toBe(6);
  });

  it('survives a non-object payload and an unknown kind', () => {
    const odd = { id: 'x', seq: 3, kind: 'mystery', meeting_time: 1, wall_time: '', payload: null } as unknown as TimelineEvent;
    const state = applyTimelineEvent(emptyTimelineState, odd);
    expect(state.lastSeq).toBe(3);
    const nullPayloadItem = { id: 'y', seq: 4, kind: 'item', meeting_time: 1, wall_time: '', payload: null } as unknown as TimelineEvent;
    expect(applyTimelineEvent(state, nullPayloadItem).lastSeq).toBe(4);
  });

  it('rejects a chat event with an invalid role without losing earlier messages', () => {
    const seeded = reduceTimeline([event(1, 'chat', { message_id: 'm1', role: 'user', text: 'hi', truncated: false, status: 'complete' })]);
    const state = applyTimelineEvent(seeded, event(2, 'chat', { message_id: 'm2', role: 'system', text: 'x' }));
    expect(state.chat.map((message) => message.id)).toEqual(['m1']);
  });
});

describe('snapshot seeding and feed selection', () => {
  const snapshot: CompanionSnapshot = {
    meeting_id: 'm1',
    session_key: 's1',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    roots: [],
    items: [makeItem('a', 10), makeItem('b', 30, { pinned: true }), makeItem('c', 20), makeItem('d', 40, { dismissed: true })],
    watches: [],
    chat: [],
    retrievals: [],
    last_seq: 9,
  };

  it('seeds lastSeq and lists from the snapshot', () => {
    const state = timelineStateFromSnapshot(snapshot);
    expect(state.lastSeq).toBe(9);
    expect(state.items).toHaveLength(4);
  });

  it('orders pinned first, then newest first, hiding dismissed items by default', () => {
    expect(selectFeedItems(snapshot.items).map((item) => item.id)).toEqual(['b', 'c', 'a']);
    expect(selectFeedItems(snapshot.items, { includeDismissed: true }).map((item) => item.id)).toEqual(['b', 'd', 'c', 'a']);
  });
});
