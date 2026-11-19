import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConversationDraftSubmission } from './conversationSessionState';
import {
  applyTokenToRequest,
  initialConversationSessionStore,
  registerSubmission,
  withThread,
} from './conversationSessionState';

function submission(): ConversationDraftSubmission {
  return {
    requestId: 'request-a',
    messageId: 'message-a',
    content: 'Hello',
    displayMarkdown: 'Hello',
    conversationId: 'conversation-1',
    modelId: 'model-1',
    filePaths: [],
    delegationOptOut: false,
    source: 'composer',
    editorHtml: 'Hello',
  };
}

function token(chunkId: number, text: string, isFinal = false) {
  return {
    event_type: 'conversation_token',
    request_id: 'request-a',
    conversation_id: 'conversation-1',
    message_id: 'assistant-a',
    chunk_id: chunkId,
    token: text,
    is_final: isFinal,
  } as never;
}

function assistantTimestamp(store: ReturnType<typeof initialConversationSessionStore>): string | undefined {
  return store.threadsByKey['conversation-1'].messages.find((message) => message.id === 'assistant-a')?.timestamp;
}

describe('applyTokenToRequest timestamps', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps the placeholder timestamp for the streamed reply across tokens', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-30T12:27:00Z'));
    let store = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission());
    store = withThread(store, 'conversation-1', (thread) => ({
      ...thread,
      messages: [
        ...thread.messages,
        {
          id: 'pending-request-a',
          role: 'assistant',
          content: '',
          timestamp: '2026-09-30T12:26:59.000Z',
          metadata: { loading: true },
        },
      ],
    }));

    vi.setSystemTime(new Date('2026-09-30T12:27:05Z'));
    const first = applyTokenToRequest(store, token(0, 'One'));
    vi.setSystemTime(new Date('2026-09-30T12:27:09Z'));
    const second = applyTokenToRequest(first.store, token(1, ' two', true));

    expect(assistantTimestamp(first.store)).toBe('2026-09-30T12:26:59.000Z');
    expect(assistantTimestamp(second.store)).toBe('2026-09-30T12:26:59.000Z');
    expect(second.store.threadsByKey['conversation-1'].messages.some((message) => message.id === 'pending-request-a')).toBe(false);
  });

  it('stamps a reply without a placeholder once, at its first token', () => {
    vi.useFakeTimers();
    const store = registerSubmission(initialConversationSessionStore(), 'conversation-1', submission());

    vi.setSystemTime(new Date('2026-09-30T12:27:05Z'));
    const first = applyTokenToRequest(store, token(0, 'One'));
    vi.setSystemTime(new Date('2026-09-30T12:27:09Z'));
    const second = applyTokenToRequest(first.store, token(1, ' two', true));

    expect(assistantTimestamp(second.store)).toBe('2026-09-30T12:27:05.000Z');
  });
});
