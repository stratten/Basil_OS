import { describe, expect, it } from 'vitest';
import { emptyTimelineState } from './companionReducer';
import {
  MAX_ASSISTANT_CONTEXT_CHARS,
  MAX_INVESTIGATION_QUESTION_CHARS,
  canInvestigate,
  investigationQuestionFromItem,
  investigationStarts,
  proposalContextText,
  unresolvedInvestigations,
} from './companionProposals';
import type { CompanionItem, TimelineEvent } from './types';

function item(id: string, text: string, overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id,
    seq: 0,
    kind: 'insight',
    text,
    confidence: 0.5,
    citations: [],
    no_source: false,
    transcript_range: { start: 0, end: 2, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...overrides,
  };
}

function retrieval(seq: number, payload: Record<string, unknown>): TimelineEvent {
  return { id: `r${seq}`, seq, kind: 'retrieval', meeting_time: seq, wall_time: '', payload };
}

describe('canInvestigate', () => {
  it('allows an ordinary note and refuses researched notes, proposals and dismissed notes', () => {
    expect(canInvestigate(item('a', 'text'))).toBe(true);
    expect(canInvestigate(item('a', 'text', { researched: true }))).toBe(false);
    expect(canInvestigate(item('a', 'text', { kind: 'proposal' }))).toBe(false);
    expect(canInvestigate(item('a', 'text', { dismissed: true }))).toBe(false);
  });
});

describe('investigationQuestionFromItem', () => {
  it('collapses whitespace and keeps a short text whole', () => {
    expect(investigationQuestionFromItem(item('a', '  Who owns\n the renewal?  '))).toBe('Who owns the renewal?');
  });

  it('cuts a long text at a word boundary within the backend limit', () => {
    const long = Array.from({ length: 120 }, (_, index) => `word${index}`).join(' ');
    const question = investigationQuestionFromItem(item('a', long));
    expect(question.length).toBeLessThanOrEqual(MAX_INVESTIGATION_QUESTION_CHARS);
    expect(long.startsWith(question)).toBe(true);
    expect(long.charAt(question.length)).toBe(' ');
  });

  it('cuts an unbroken text hard at the limit', () => {
    expect(investigationQuestionFromItem(item('a', 'x'.repeat(900)))).toHaveLength(MAX_INVESTIGATION_QUESTION_CHARS);
  });

  it('returns an empty question for a blank note', () => {
    expect(investigationQuestionFromItem(item('a', '   '))).toBe('');
  });
});

describe('investigations in the timeline', () => {
  const timeline = {
    ...emptyTimelineState,
    retrievals: [
      retrieval(1, { purpose: 'investigation', investigation_id: 'inv-1', queries: ['renewal date'] }),
      retrieval(2, { purpose: 'periodic', queries: ['unrelated'] }),
      retrieval(3, { purpose: 'investigation', investigation_id: 'inv-2', queries: ['vendor quotes'] }),
      retrieval(4, { purpose: 'investigation', queries: ['no id'] }),
    ],
    items: [item('a1', 'Answer', { investigation_id: 'inv-1', researched: true })],
  };

  it('lists only investigation retrievals that carry an id', () => {
    expect(investigationStarts(timeline)).toEqual([
      { id: 'inv-1', question: 'renewal date' },
      { id: 'inv-2', question: 'vendor quotes' },
    ]);
  });

  it('leaves out an investigation that already produced an item', () => {
    expect(unresolvedInvestigations(timeline)).toEqual([{ id: 'inv-2', question: 'vendor quotes' }]);
  });
});

describe('proposalContextText', () => {
  const answer = item('a1', '  The renewal date is 3 March.  ', { investigation_id: 'inv-1', researched: true });
  const proposal = item('p1', 'Add a reminder', { kind: 'proposal', investigation_id: 'inv-1' });

  it('uses the researched answer of the same investigation', () => {
    expect(proposalContextText([proposal, answer], proposal)).toBe('The renewal date is 3 March.');
  });

  it('is empty when the proposal has no investigation or its answer is missing', () => {
    expect(proposalContextText([answer], item('p2', 'x', { kind: 'proposal' }))).toBe('');
    expect(proposalContextText([proposal], proposal)).toBe('');
  });

  it('bounds the context to the hand-off limit', () => {
    const big = item('a2', 'y'.repeat(MAX_ASSISTANT_CONTEXT_CHARS + 500), { investigation_id: 'inv-1' });
    expect(proposalContextText([big], proposal)).toHaveLength(MAX_ASSISTANT_CONTEXT_CHARS);
  });
});
