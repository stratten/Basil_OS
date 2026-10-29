import { describe, expect, it } from 'vitest';
import { countKindFilters, hideFoldedAnswers, itemMatchesKindFilter, selectChatPairs, selectCompanionStream, selectPinnedItems, selectProposalsAwaitingDecision, selectUnseenEntries } from './companionStreamSelectors';
import type { ChatMessage, CompanionItem } from './types';

function item(id: string, seq: number, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id,
    seq,
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
    ...overrides,
  };
}

function message(id: string, seq: number, role: ChatMessage['role'] = 'user'): ChatMessage {
  return { id, seq, role, text: id, meeting_time: 0, truncated: false, status: 'complete' };
}

describe('selectCompanionStream', () => {
  it('merges items and chat by arrival, oldest first, regardless of transcript time', () => {
    const late = item('late-researched', 9, { transcript_range: { start: 1, end: 2, turn_ids: [] } });
    const early = item('early', 3, { transcript_range: { start: 100, end: 120, turn_ids: [] } });
    const stream = selectCompanionStream({ items: [late, early], chat: [message('q', 5), message('a', 6, 'assistant')] });
    expect(stream.map((entry) => entry.key)).toEqual(['item:early', 'chat:q', 'chat:a', 'item:late-researched']);
  });

  it('hides dismissed items unless asked and keeps a pinned item in its chronological place', () => {
    const items = [item('a', 1), item('b', 2, { dismissed: true }), item('c', 3, { pinned: true })];
    expect(selectCompanionStream({ items, chat: [] }).map((entry) => entry.key)).toEqual(['item:a', 'item:c']);
    expect(selectCompanionStream({ items, chat: [] }, { includeDismissed: true }).map((entry) => entry.key)).toEqual(['item:a', 'item:b', 'item:c']);
  });

  it('puts streaming and pending assistant replies at the end and drops any that already persisted', () => {
    const stream = selectCompanionStream(
      { items: [item('a', 1)], chat: [message('q', 2), message('done', 3, 'assistant')] },
      { drafts: { live: 'partial', done: 'stale draft' }, pendingAssistantIds: ['wait', 'done', 'live'] },
    );
    expect(stream.map((entry) => `${entry.type}:${entry.key}`)).toEqual(['item:item:a', 'chat:chat:q', 'chat:chat:done', 'draft:chat:live', 'pending:chat:wait']);
  });

  it('is empty for an empty timeline', () => {
    expect(selectCompanionStream({ items: [], chat: [] })).toEqual([]);
  });
});

describe('unseen and pinned selection', () => {
  it('counts only persisted rows newer than the last seen seq, never the reader\'s own messages or drafts', () => {
    const stream = selectCompanionStream(
      { items: [item('old', 2), item('new', 8)], chat: [message('mine', 9), message('reply', 10, 'assistant')] },
      { drafts: { live: 'x' } },
    );
    expect(selectUnseenEntries(stream, 5).map((entry) => entry.key)).toEqual(['item:new', 'chat:reply']);
    expect(selectUnseenEntries(stream, 10)).toEqual([]);
  });

  it('lists pinned, undismissed items in arrival order', () => {
    const items = [item('b', 4, { pinned: true }), item('a', 2, { pinned: true }), item('gone', 3, { pinned: true, dismissed: true }), item('plain', 1)];
    expect(selectPinnedItems(items).map((entry) => entry.id)).toEqual(['a', 'b']);
  });

  it('finds proposals that still need a decision', () => {
    const proposal = (id: string, state: 'proposed' | 'started') =>
      item(id, 1, {
        kind: 'proposal',
        proposal: { proposal_id: id, action: 'todo', title: 't', instruction: 'i', authority: 'review', state, todo_id: null, agent_task_id: null, error: null, auto_started: false },
      });
    const waiting = selectProposalsAwaitingDecision([proposal('p1', 'proposed'), proposal('p2', 'started'), item('plain', 2)]);
    expect(waiting.map((entry) => entry.id)).toEqual(['p1']);
  });
});

describe('kind filter', () => {
  const items = [
    item('s1', 1, { kind: 'suggestion' }),
    item('a1', 2, { kind: 'answer', pinned: true }),
    item('c1', 3, { kind: 'context_note' }),
    item('i1', 4, { kind: 'insight' }),
    item('gone', 5, { kind: 'answer', dismissed: true, pinned: true }),
  ];
  const keys = (filter: Parameters<typeof itemMatchesKindFilter>[1]) => selectCompanionStream({ items, chat: [message('q', 6)] }, { kindFilter: filter }).map((entry) => entry.key);

  it('shows every kind under All and only the chosen kind otherwise, never touching the conversation', () => {
    expect(keys('all')).toEqual(['item:s1', 'item:a1', 'item:c1', 'item:i1', 'chat:q']);
    expect(keys('suggestion')).toEqual(['item:s1', 'chat:q']);
    expect(keys('answer')).toEqual(['item:a1', 'chat:q']);
    expect(keys('context_note')).toEqual(['item:c1', 'chat:q']);
    expect(keys('pinned')).toEqual(['item:a1', 'chat:q']);
  });

  it('counts each filter without dismissed items', () => {
    expect(countKindFilters(items)).toEqual({ all: 4, suggestion: 1, answer: 1, context_note: 1, pinned: 1 });
    expect(countKindFilters([])).toEqual({ all: 0, suggestion: 0, answer: 0, context_note: 0, pinned: 0 });
  });

  it('never hides a proposal that is waiting for a decision, but filters a decided one', () => {
    const proposal = (state: 'proposed' | 'started') => item('p', 7, { kind: 'proposal', proposal: { action: 'todo', title: 't', instruction: 'i', authority: 'review', state } as CompanionItem['proposal'] });
    expect(itemMatchesKindFilter(proposal('proposed'), 'answer')).toBe(true);
    expect(itemMatchesKindFilter(proposal('proposed'), 'pinned')).toBe(true);
    expect(itemMatchesKindFilter(proposal('started'), 'answer')).toBe(false);
    expect(itemMatchesKindFilter(proposal('started'), 'all')).toBe(true);
  });
});


describe('chat pairs', () => {
  const stream = () =>
    selectCompanionStream(
      {
        items: [item('card', 3)],
        chat: [message('q1', 1), message('a1', 2, 'assistant'), message('q2', 4), message('a2', 5, 'assistant'), message('q3', 6)],
      },
      { pendingAssistantIds: ['a3'] },
    );

  it('pairs each saved answer with the latest question before it and leaves unanswered questions out', () => {
    const pairs = selectChatPairs(stream());
    expect(Array.from(pairs.answerKeysByQuestion)).toEqual([['q1', ['chat:a1']], ['q2', ['chat:a2']]]);
    expect(pairs.questionByAnswerKey.get('chat:a2')).toBe('q2');
    expect(pairs.answerKeysByQuestion.has('q3')).toBe(false);
  });

  it('keeps several answers to one question together, and ignores an answer with no question before it', () => {
    const entries = selectCompanionStream({ items: [], chat: [message('orphan', 1, 'assistant'), message('q', 2), message('a', 3, 'assistant'), message('b', 4, 'assistant')] });
    const pairs = selectChatPairs(entries);
    expect(pairs.answerKeysByQuestion.get('q')).toEqual(['chat:a', 'chat:b']);
    expect(pairs.questionByAnswerKey.has('chat:orphan')).toBe(false);
  });

  it('hides only the answers of folded questions and keeps every card and question in place', () => {
    const entries = stream();
    const pairs = selectChatPairs(entries);
    expect(hideFoldedAnswers(entries, pairs, []).map((entry) => entry.key)).toEqual(entries.map((entry) => entry.key));
    expect(hideFoldedAnswers(entries, pairs, ['q1']).map((entry) => entry.key)).toEqual(['chat:q1', 'item:card', 'chat:q2', 'chat:a2', 'chat:q3', 'chat:a3']);
    expect(hideFoldedAnswers(entries, pairs, ['q3', 'unknown'])).toBe(entries);
  });
});
