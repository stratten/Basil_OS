import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { applyProposalUpdate, applyTimelineEvent, emptyTimelineState, reduceTimeline } from './companionReducer';
import type { CompanionItem, CompanionProposalInfo, TimelineEvent } from './types';

const FIXTURE_PATH = resolve(
  import.meta.dirname,
  '../../../../backend/src/tests/services/meeting_companion_tests/fixtures/timeline_parity_proposals.json',
);

interface ProposalParityFixture {
  events: TimelineEvent[];
  expected: {
    items: Array<{ id: string; kind: string; dismissed: boolean }>;
    proposals: Array<{ item_id: string; state: string; todo_id: string | null; agent_task_id: string | null; error: string | null; auto_started: boolean }>;
    last_seq: number;
  };
}

function loadFixture(): ProposalParityFixture {
  return JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as ProposalParityFixture;
}

function proposalInfo(overrides: Partial<CompanionProposalInfo> = {}): CompanionProposalInfo {
  return {
    proposal_id: 'pr-1',
    action: 'todo',
    title: 'Add a reminder',
    instruction: 'Remind me to renew.',
    authority: 'review',
    state: 'proposed',
    todo_id: null,
    agent_task_id: null,
    error: null,
    auto_started: false,
    ...overrides,
  };
}

function proposalItem(id: string, proposal: CompanionProposalInfo | null = proposalInfo()): CompanionItem {
  return {
    id,
    kind: 'proposal',
    text: 'Add a reminder',
    confidence: 0.9,
    citations: [],
    no_source: false,
    transcript_range: { start: 1, end: 3, turn_ids: [] },
    trigger: 'investigation',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...(proposal === null ? {} : { proposal }),
  };
}

function proposalEvent(seq: number, payload: Record<string, unknown>): TimelineEvent {
  return { id: `p${seq}`, seq, kind: 'proposal', meeting_time: seq, wall_time: '2026-01-01T00:00:00.000000Z', payload };
}

describe('companion reducer parity with the Python proposal events', () => {
  it('derives the same proposal states as the shared fixture expects', () => {
    const fixture = loadFixture();
    const state = reduceTimeline(fixture.events);
    expect(state.items.map((item) => ({ id: item.id, kind: item.kind, dismissed: item.dismissed }))).toEqual(fixture.expected.items);
    expect(
      state.items.map((item) => ({
        item_id: item.id,
        state: item.proposal?.state,
        todo_id: item.proposal?.todo_id,
        agent_task_id: item.proposal?.agent_task_id,
        error: item.proposal?.error,
        auto_started: item.proposal?.auto_started,
      })),
    ).toEqual(fixture.expected.proposals);
    expect(state.lastSeq).toBe(fixture.expected.last_seq);
  });

  it('keeps the fixture at the documented size so a silent truncation is noticed', () => {
    expect(loadFixture().events).toHaveLength(14);
  });
});

describe('applyProposalUpdate', () => {
  it('keeps a failed proposal open so a retry can still start it', () => {
    const failed = applyProposalUpdate([proposalItem('i1')], { item_id: 'i1', state: 'failed', error: 'Not ready.' });
    expect(failed[0].proposal).toMatchObject({ state: 'failed', error: 'Not ready.' });
    const started = applyProposalUpdate(failed, { item_id: 'i1', state: 'started', todo_id: 't-1' });
    expect(started[0].proposal).toMatchObject({ state: 'started', todo_id: 't-1', error: null });
  });

  it('uses the default sentence when a failure carries no error text', () => {
    const failed = applyProposalUpdate([proposalItem('i1')], { item_id: 'i1', state: 'failed' });
    expect(failed[0].proposal?.error).toBe('The action could not be started.');
  });

  it('ignores a late update once the proposal is decided', () => {
    for (const final of ['started', 'handed_off', 'dismissed'] as const) {
      const items = [proposalItem('i1', proposalInfo({ state: final }))];
      expect(applyProposalUpdate(items, { item_id: 'i1', state: 'failed', error: 'late' })).toBe(items);
    }
  });

  it('ignores an unknown item, a plain item, an unknown state and a missing state', () => {
    const items = [proposalItem('i1'), proposalItem('plain', null)];
    expect(applyProposalUpdate(items, { item_id: 'zz', state: 'started' })).toBe(items);
    expect(applyProposalUpdate(items, { item_id: 'plain', state: 'started' })).toBe(items);
    expect(applyProposalUpdate(items, { item_id: 'i1', state: 'bogus' })).toBe(items);
    expect(applyProposalUpdate(items, { item_id: 'i1' })).toBe(items);
  });

  it('marks an automatic start and clears the pin when dismissed', () => {
    const started = applyProposalUpdate([proposalItem('i1')], { item_id: 'i1', state: 'started', todo_id: 't-1', auto: true });
    expect(started[0].proposal?.auto_started).toBe(true);
    const pinned = [{ ...proposalItem('i2'), pinned: true }];
    const dismissed = applyProposalUpdate(pinned, { item_id: 'i2', state: 'dismissed' });
    expect(dismissed[0]).toMatchObject({ dismissed: true, pinned: false });
  });

  it('is applied by the timeline reducer and a malformed event still advances the sequence', () => {
    const state = applyTimelineEvent(emptyTimelineState, proposalEvent(4, {}));
    expect(state.items).toEqual([]);
    expect(state.lastSeq).toBe(4);
  });
});

describe('parsing a proposal item', () => {
  it('keeps the proposal and the research fields of an item that has them', () => {
    const wire = { ...proposalItem('i1'), researched: true, investigation_id: 'inv-1', evidence_count: 3 };
    const state = applyTimelineEvent(emptyTimelineState, { id: 'e1', seq: 1, kind: 'item', meeting_time: 1, wall_time: '', payload: { item: wire } });
    expect(state.items[0]).toMatchObject({ kind: 'proposal', researched: true, investigation_id: 'inv-1', evidence_count: 3, proposal: { action: 'todo', state: 'proposed' } });
  });

  it('adds no research fields to an item saved before investigations existed', () => {
    const old = { ...proposalItem('i1', null), kind: 'insight' };
    const state = applyTimelineEvent(emptyTimelineState, { id: 'e1', seq: 1, kind: 'item', meeting_time: 1, wall_time: '', payload: { item: old } });
    expect(Object.keys(state.items[0])).not.toContain('researched');
    expect(Object.keys(state.items[0])).not.toContain('proposal');
  });

  it('drops a proposal block whose action is not one the Companion can propose', () => {
    const wire = { ...proposalItem('i1'), proposal: { ...proposalInfo(), action: 'send_email' } };
    const state = applyTimelineEvent(emptyTimelineState, { id: 'e1', seq: 1, kind: 'item', meeting_time: 1, wall_time: '', payload: { item: wire } });
    expect(state.items[0].proposal).toBeUndefined();
  });
});
