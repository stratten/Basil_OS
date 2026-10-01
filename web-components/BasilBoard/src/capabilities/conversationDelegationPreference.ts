import type { ConversationMessageItem } from '../contracts';
import {
  DRAFT_THREAD_KEY,
  isPendingConversationThreadKey,
  type ConversationThreadSession,
} from './conversationSessionState';

export function resolveThreadDelegationOptOut(
  thread: ConversationThreadSession,
  defaultConversationOnly: boolean,
): boolean {
  if (thread.delegationOptOutSource) return thread.delegationOptOut;
  if (thread.key === DRAFT_THREAD_KEY || isPendingConversationThreadKey(thread.key)) return defaultConversationOnly;
  return thread.delegationOptOut;
}

export function delegationOptOutFromHistory(messages: readonly ConversationMessageItem[]): boolean | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== 'user') continue;
    const value = message.metadata?.delegation_opt_out;
    return typeof value === 'boolean' ? value : undefined;
  }
  return undefined;
}

export function withHistoryDelegationOptOut(
  thread: ConversationThreadSession,
  messages: readonly ConversationMessageItem[],
): ConversationThreadSession {
  if (thread.delegationOptOutSource === 'user') return thread;
  const restored = delegationOptOutFromHistory(messages);
  if (restored === undefined) return thread;
  return { ...thread, delegationOptOut: restored, delegationOptOutSource: 'resolved' };
}
