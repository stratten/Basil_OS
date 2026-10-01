import { describe, expect, it } from 'vitest';
import type { ConversationMessageItem } from '../contracts';
import {
  delegationOptOutFromHistory,
  resolveThreadDelegationOptOut,
  withHistoryDelegationOptOut,
} from './conversationDelegationPreference';
import {
  DRAFT_THREAD_KEY,
  createDraftThreadSession,
  pendingConversationThreadKey,
} from './conversationSessionState';

function message(id: string, role: string, metadata: Record<string, unknown> = {}): ConversationMessageItem {
  return { id, role, content: id, timestamp: '2026-09-30T12:00:00Z', metadata };
}

describe('resolveThreadDelegationOptOut', () => {
  it('uses the default for the draft and pending threads until a source is set', () => {
    expect(resolveThreadDelegationOptOut(createDraftThreadSession(DRAFT_THREAD_KEY), true)).toBe(true);
    expect(resolveThreadDelegationOptOut(createDraftThreadSession(pendingConversationThreadKey('r1')), true)).toBe(true);
    expect(resolveThreadDelegationOptOut(createDraftThreadSession(DRAFT_THREAD_KEY), false)).toBe(false);
  });

  it('keeps a user choice on a new thread even when the default differs', () => {
    const thread = { ...createDraftThreadSession(DRAFT_THREAD_KEY), delegationOptOut: false, delegationOptOutSource: 'user' as const };
    expect(resolveThreadDelegationOptOut(thread, true)).toBe(false);
  });

  it('ignores the default for an existing conversation', () => {
    expect(resolveThreadDelegationOptOut(createDraftThreadSession('conversation-1'), true)).toBe(false);
  });
});

describe('delegationOptOutFromHistory', () => {
  it('reads the last user message only', () => {
    expect(delegationOptOutFromHistory([
      message('u1', 'user', { delegation_opt_out: false }),
      message('a1', 'assistant', { delegation_opt_out: false }),
      message('u2', 'user', { delegation_opt_out: true }),
      message('a2', 'assistant'),
    ])).toBe(true);
  });

  it('returns undefined for empty history, missing keys, and malformed values', () => {
    expect(delegationOptOutFromHistory([])).toBeUndefined();
    expect(delegationOptOutFromHistory([message('u1', 'user', { delegation_opt_out: true }), message('u2', 'user')])).toBeUndefined();
    expect(delegationOptOutFromHistory([message('u1', 'user', { delegation_opt_out: 'yes' })])).toBeUndefined();
  });
});

describe('withHistoryDelegationOptOut', () => {
  it('restores the value and marks it resolved', () => {
    const restored = withHistoryDelegationOptOut(createDraftThreadSession('conversation-1'), [message('u1', 'user', { delegation_opt_out: true })]);
    expect(restored.delegationOptOut).toBe(true);
    expect(restored.delegationOptOutSource).toBe('resolved');
  });

  it('does not override a manual choice', () => {
    const thread = { ...createDraftThreadSession('conversation-1'), delegationOptOut: false, delegationOptOutSource: 'user' as const };
    expect(withHistoryDelegationOptOut(thread, [message('u1', 'user', { delegation_opt_out: true })])).toBe(thread);
  });

  it('leaves the thread unchanged when history has no value', () => {
    const thread = createDraftThreadSession('conversation-1');
    expect(withHistoryDelegationOptOut(thread, [message('u1', 'user')])).toBe(thread);
  });
});
