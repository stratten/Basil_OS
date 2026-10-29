import { describe, expect, it } from 'vitest';
import { chatResearchTarget, replyQuote } from './companionChatResearch';
import { emptyTimelineState, type CompanionTimelineState } from './companionReducer';
import type { ChatMessage, CompanionItem, TimelineEvent } from './types';

const message = (id: string, seq: number, role: ChatMessage['role'], text: string, overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  id, seq, role, text, meeting_time: 1, truncated: false, status: 'complete', ...overrides,
});

const researched = (id: string, replyTo: string): CompanionItem => ({
  id, seq: 9, kind: 'answer', text: 'Twelve months.', confidence: 0.9, citations: [], no_source: false,
  transcript_range: { start: 0, end: 1, turn_ids: [] }, trigger: 'investigation', watch_id: null, truncated: false, pinned: false, dismissed: false,
  researched: true, reply_to_message_id: replyTo,
});

function timeline(chat: ChatMessage[], extra: Partial<CompanionTimelineState> = {}): CompanionTimelineState {
  return { ...emptyTimelineState, chat, ...extra };
}

const start = (id: string, question: string): TimelineEvent => ({
  id: `e-${id}`, seq: 5, at: 0, meeting_time: 0, kind: 'retrieval', payload: { purpose: 'investigation', investigation_id: id, queries: [question] },
} as unknown as TimelineEvent);

describe('chatResearchTarget', () => {
  const chat = [message('q1', 1, 'user', 'What is the Acme renewal term?'), message('a1', 2, 'assistant', 'I could not find that in the transcript.')];

  it('offers the nearest earlier question for an answer that cited nothing', () => {
    expect(chatResearchTarget(timeline(chat), chat[1])).toEqual({ question: 'What is the Acme renewal term?', replyToMessageId: 'q1' });
    const later = [...chat, message('q2', 3, 'user', 'And the notice period?'), message('a2', 4, 'assistant', 'Not mentioned.')];
    expect(chatResearchTarget(timeline(later), later[3])?.replyToMessageId).toBe('q2');
    expect(chatResearchTarget(timeline(later), later[1])?.replyToMessageId).toBe('q1');
  });

  it('is not offered for the reader, an error, a cut-off answer, or an empty answer', () => {
    expect(chatResearchTarget(timeline(chat), chat[0])).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], status: 'error' })).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], truncated: true })).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: '   ' })).toBeNull();
  });

  it('is not offered for an answer that cited its sources', () => {
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: 'It caps at five [proj/retry.py:3-9].' })).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: 'See [proj/retry.py:12] for the cap.' })).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: 'Use the [docs] link, at 10:30.' })).not.toBeNull();
  });

  it('is not offered when a search was already started or refused by the reply itself', () => {
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: 'Looking into: the renewal term. I will add what I find to the feed.' })).toBeNull();
    expect(chatResearchTarget(timeline(chat), { ...chat[1], text: "Not here.\n\nI'm looking into this in your sources and will add what I find to the feed." })).toBeNull();
  });

  it('is not offered once the question has a researched answer or is being researched', () => {
    expect(chatResearchTarget(timeline(chat, { items: [researched('r1', 'q1')] }), chat[1])).toBeNull();
    expect(chatResearchTarget(timeline(chat, { retrievals: [start('iv-1', 'What is the Acme renewal term?')] }), chat[1])).toBeNull();
    expect(chatResearchTarget(timeline(chat, { retrievals: [start('iv-1', 'A different question entirely')] }), chat[1])).not.toBeNull();
  });

  it('is not offered when no earlier reader message exists, and cuts a very long question', () => {
    expect(chatResearchTarget(timeline([chat[1]]), chat[1])).toBeNull();
    const long = [message('q1', 1, 'user', `${'word '.repeat(120)}end`), chat[1]];
    const target = chatResearchTarget(timeline(long), long[1]);
    expect(target?.question.length).toBeLessThanOrEqual(300);
    expect(target?.question.endsWith('word')).toBe(true);
  });
});

describe('replyQuote', () => {
  const chat = [message('q1', 1, 'user', '  What is   the renewal\nterm? '), message('a1', 2, 'assistant', 'Reply')];

  it('quotes the reader message flattened and nothing for a missing, assistant or absent id', () => {
    expect(replyQuote(timeline(chat), 'q1')).toBe('What is the renewal term?');
    expect(replyQuote(timeline(chat), 'a1')).toBeNull();
    expect(replyQuote(timeline(chat), 'gone')).toBeNull();
    expect(replyQuote(timeline(chat), null)).toBeNull();
    expect(replyQuote(timeline(chat), undefined)).toBeNull();
    expect(replyQuote(timeline(chat), '')).toBeNull();
  });
});
