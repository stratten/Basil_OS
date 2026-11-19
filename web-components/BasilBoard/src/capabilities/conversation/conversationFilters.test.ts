import { describe, expect, it } from 'vitest';
import {
  EMPTY_CONVERSATION_FILTERS,
  countActiveConversationFilters,
  hasActiveConversationFilters,
  toConversationFilterParams,
} from './conversationFilters';

describe('conversation filters', () => {
  it('sends nothing and counts nothing when no filter is set', () => {
    expect(toConversationFilterParams(EMPTY_CONVERSATION_FILTERS)).toEqual({});
    expect(countActiveConversationFilters(EMPTY_CONVERSATION_FILTERS)).toBe(0);
    expect(hasActiveConversationFilters(EMPTY_CONVERSATION_FILTERS)).toBe(false);
  });

  it('maps each condition to its wire parameter and counts it once', () => {
    const filters = { startDate: '2026-03-02', endDate: '2026-03-03', agentWork: 'failed', length: 'multi' } as const;
    expect(toConversationFilterParams(filters)).toEqual({
      start_date: new Date(2026, 2, 2, 0, 0, 0, 0).toISOString(),
      end_date: new Date(2026, 2, 3, 23, 59, 59, 999).toISOString(),
      agent_work: 'failed',
      length: 'multi',
    });
    expect(countActiveConversationFilters(filters)).toBe(4);
  });

  it('sends the wire value "any" for the panel choice "Used an agent" and nothing for "Any"', () => {
    expect(toConversationFilterParams({ ...EMPTY_CONVERSATION_FILTERS, agentWork: 'has' })).toEqual({ agent_work: 'any' });
    expect(toConversationFilterParams({ ...EMPTY_CONVERSATION_FILTERS, agentWork: 'none' })).toEqual({ agent_work: 'none' });
    expect(toConversationFilterParams({ ...EMPTY_CONVERSATION_FILTERS, agentWork: 'any' })).toEqual({});
  });

  it('ignores a malformed date instead of sending it', () => {
    expect(toConversationFilterParams({ ...EMPTY_CONVERSATION_FILTERS, startDate: 'not-a-date' })).toEqual({});
  });
});
