import { describe, expect, it } from 'vitest';
import { MAX_BUFFERED_EVENTS, companionStoreReducer, initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import { EMPTY_COMPANION_STATUS, type CompanionItem, type CompanionSnapshot, type TimelineEvent } from './types';

function item(id: string): CompanionItem {
  return {
    id,
    seq: 0,
    kind: 'insight',
    text: id,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: 0, end: 1, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
  };
}

function itemEvent(seq: number, id: string): TimelineEvent {
  return { id: `e${seq}`, seq, kind: 'item', meeting_time: seq, wall_time: '', payload: { item: item(id) } };
}

function chatEvent(seq: number, messageId: string, role: 'user' | 'assistant', text: string): TimelineEvent {
  return { id: `e${seq}`, seq, kind: 'chat', meeting_time: seq, wall_time: '', payload: { message_id: messageId, role, text, truncated: false, status: 'complete' } };
}

function snapshot(lastSeq: number, overrides: Partial<CompanionSnapshot> = {}): CompanionSnapshot {
  return {
    meeting_id: 'm1',
    session_key: 's1',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    roots: [],
    items: [],
    watches: [],
    chat: [],
    retrievals: [],
    last_seq: lastSeq,
    ...overrides,
  };
}

function ready(lastSeq = 0, overrides: Partial<CompanionSnapshot> = {}): CompanionStoreState {
  return companionStoreReducer(companionStoreReducer(initialCompanionStoreState, { type: 'reset', phase: 'loading' }), {
    type: 'hydrated',
    snapshot: snapshot(lastSeq, overrides),
  });
}

describe('companionStoreReducer sequencing', () => {
  it('applies the next event and ignores a duplicate', () => {
    const once = companionStoreReducer(ready(0), { type: 'event', event: itemEvent(1, 'a') });
    expect(once.timeline.items.map((entry) => entry.id)).toEqual(['a']);
    const twice = companionStoreReducer(once, { type: 'event', event: itemEvent(1, 'a') });
    expect(twice).toBe(once);
  });

  it('flags a resync on a gap and does not apply the out-of-order event', () => {
    const state = companionStoreReducer(ready(0), { type: 'event', event: itemEvent(3, 'c') });
    expect(state.resyncNeeded).toBe(true);
    expect(state.timeline.items).toEqual([]);
  });

  it('buffers events that arrive before hydration and replays them in order after it', () => {
    let state = companionStoreReducer(initialCompanionStoreState, { type: 'reset', phase: 'loading' });
    state = companionStoreReducer(state, { type: 'event', event: itemEvent(5, 'e') });
    state = companionStoreReducer(state, { type: 'event', event: itemEvent(4, 'd') });
    state = companionStoreReducer(state, { type: 'event', event: itemEvent(3, 'old') });
    expect(state.buffer).toHaveLength(3);
    state = companionStoreReducer(state, { type: 'hydrated', snapshot: snapshot(3, { items: [item('old')] }) });
    expect(state.timeline.items.map((entry) => entry.id)).toEqual(['old', 'd', 'e']);
    expect(state.timeline.lastSeq).toBe(5);
    expect(state.buffer).toEqual([]);
  });

  it('caps the pre-hydration buffer', () => {
    let state = companionStoreReducer(initialCompanionStoreState, { type: 'reset', phase: 'loading' });
    for (let seq = 1; seq <= MAX_BUFFERED_EVENTS + 3; seq += 1) {
      state = companionStoreReducer(state, { type: 'event', event: itemEvent(seq, `i${seq}`) });
    }
    expect(state.buffer).toHaveLength(MAX_BUFFERED_EVENTS);
    expect(state.buffer[0].seq).toBe(4);
  });

  it('clears the resync flag when a snapshot lands or a reload fails', () => {
    const flagged = companionStoreReducer(ready(0), { type: 'event', event: itemEvent(9, 'z') });
    expect(companionStoreReducer(flagged, { type: 'hydrated', snapshot: snapshot(9) }).resyncNeeded).toBe(false);
    const failed = companionStoreReducer(flagged, { type: 'loadFailed', message: 'down' });
    expect(failed.resyncNeeded).toBe(false);
    expect(failed.phase).toBe('ready');
    expect(failed.loadError).toBe('down');
  });

  it('moves a never-loaded store to the error phase on failure', () => {
    const loading = companionStoreReducer(initialCompanionStoreState, { type: 'reset', phase: 'loading' });
    expect(companionStoreReducer(loading, { type: 'loadFailed', message: 'down' }).phase).toBe('error');
  });
});

describe('companionStoreReducer chat streaming', () => {
  it('shows a pending assistant id, then a draft, then the persisted message', () => {
    let state = ready(0);
    state = companionStoreReducer(state, { type: 'chatPending', messageId: 'a1' });
    expect(state.pendingAssistantIds).toEqual(['a1']);
    state = companionStoreReducer(state, { type: 'chatDelta', messageId: 'a1', textDelta: 'Hel' });
    state = companionStoreReducer(state, { type: 'chatDelta', messageId: 'a1', textDelta: 'lo' });
    expect(state.drafts).toEqual({ a1: 'Hello' });
    expect(state.pendingAssistantIds).toEqual([]);
    state = companionStoreReducer(state, { type: 'event', event: chatEvent(1, 'a1', 'assistant', 'Hello there') });
    expect(state.drafts).toEqual({});
    expect(state.timeline.chat.map((message) => message.text)).toEqual(['Hello there']);
  });

  it('does not re-add a pending id for a message that is already persisted or streaming', () => {
    const persisted = ready(1, { chat: [{ id: 'a1', role: 'assistant', text: 'x', meeting_time: 1, truncated: false, status: 'complete', seq: 0 }] });
    expect(companionStoreReducer(persisted, { type: 'chatPending', messageId: 'a1' })).toBe(persisted);
    const streaming = companionStoreReducer(ready(0), { type: 'chatDelta', messageId: 'a2', textDelta: 'x' });
    expect(companionStoreReducer(streaming, { type: 'chatPending', messageId: 'a2' })).toBe(streaming);
  });

  it('drops drafts for messages that a later snapshot already contains', () => {
    let state = companionStoreReducer(ready(0), { type: 'chatDelta', messageId: 'a1', textDelta: 'partial' });
    state = companionStoreReducer(state, {
      type: 'hydrated',
      snapshot: snapshot(2, { chat: [{ id: 'a1', role: 'assistant', text: 'full', meeting_time: 2, truncated: false, status: 'complete', seq: 0 }] }),
    });
    expect(state.drafts).toEqual({});
  });

  it('merges a partial status frame over the snapshot status', () => {
    const state = companionStoreReducer(ready(0), { type: 'status', status: { capacity: 'paused', capacity_reason: 'lag' } });
    expect(state.status).toMatchObject({ live: true, enabled: true, capacity: 'paused', capacity_reason: 'lag' });
  });
});
