import { describe, expect, it } from 'vitest';
import { companionStoreReducer, initialCompanionStoreState } from './companionStore';
import { emptyTimelineState } from './companionReducer';
import type { CompanionItem, CompanionProposalResult } from './types';

const proposalItem: CompanionItem = {
  id: 'i1',
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
  proposal: {
    proposal_id: 'pr-1',
    action: 'todo',
    title: 'Add a reminder',
    instruction: 'Remind me.',
    authority: 'review',
    state: 'proposed',
    todo_id: null,
    agent_task_id: null,
    error: null,
    auto_started: false,
  },
};

const withProposal = { ...initialCompanionStoreState, timeline: { ...emptyTimelineState, items: [proposalItem] } };

function result(overrides: Partial<CompanionProposalResult>): CompanionProposalResult {
  return { state: 'started', title: 'Add a reminder', instruction: 'Remind me.', todo_id: 't-1', agent_task_id: null, error: null, ...overrides };
}

describe('companionStoreReducer proposalResult', () => {
  it('records a started proposal with its To-Do id', () => {
    const next = companionStoreReducer(withProposal, { type: 'proposalResult', itemId: 'i1', result: result({}) });
    expect(next.timeline.items[0].proposal).toMatchObject({ state: 'started', todo_id: 't-1' });
  });

  it('records a failed start with the backend error so Try Again can show', () => {
    const next = companionStoreReducer(withProposal, { type: 'proposalResult', itemId: 'i1', result: result({ state: 'failed', todo_id: null, error: 'Not ready.' }) });
    expect(next.timeline.items[0].proposal).toMatchObject({ state: 'failed', error: 'Not ready.' });
  });

  it('dismisses the item when the answer is dismissed', () => {
    const next = companionStoreReducer(withProposal, { type: 'proposalResult', itemId: 'i1', result: result({ state: 'dismissed', todo_id: null }) });
    expect(next.timeline.items[0].dismissed).toBe(true);
  });

  it('returns the same state for an unknown item', () => {
    expect(companionStoreReducer(withProposal, { type: 'proposalResult', itemId: 'zz', result: result({}) })).toBe(withProposal);
  });

  it('does not change a proposal that a live event already decided', () => {
    const decided = companionStoreReducer(withProposal, { type: 'proposalResult', itemId: 'i1', result: result({}) });
    expect(companionStoreReducer(decided, { type: 'proposalResult', itemId: 'i1', result: result({ state: 'failed', error: 'late' }) })).toBe(decided);
  });
});
