import { describe, expect, it, vi } from 'vitest';
import type { ConversationMessageItem, WSEvent } from '../contracts';
import {
  acceptsConversationEvent,
  acceptsPersistedConversationEvent,
  conversationAttachments,
  conversationDisplayMarkdown,
  formatConversationTimestamp,
  initialConversationStreamState,
  reduceConversationToken,
} from './chatsPresentation';

function message(metadata: Record<string, unknown>): ConversationMessageItem {
  return {
    id: 'message-1',
    role: 'user',
    content: 'plain <text> & symbols',
    timestamp: '2026-07-30T12:00:00Z',
    metadata,
  };
}

function token(
  chunkId: number,
  value: string,
  isFinal = false,
): WSEvent {
  return {
    event_type: 'conversation_token',
    request_id: 'request-1',
    conversation_id: 'conversation-1',
    message_id: 'assistant-1',
    chunk_id: chunkId,
    token: value,
    is_final: isFinal,
  };
}

describe('chatsPresentation', () => {
  it('uses durable display Markdown and preserves special characters', () => {
    expect(conversationDisplayMarkdown(message({
      display_markdown: '**bold** <u>underlined</u> & literal',
    }))).toBe('**bold** <u>underlined</u> & literal');
    expect(conversationDisplayMarkdown(message({}))).toBe('plain <text> & symbols');
    expect(conversationDisplayMarkdown(message({ display_markdown: 42 }))).toBe('plain <text> & symbols');
  });

  it('accepts only complete attachment metadata records', () => {
    expect(conversationAttachments(message({
      attached_files: [
        {
          filename: 'a.txt',
          path: '/tmp/a.txt',
          file_type: 'txt',
          file_size: 12,
        },
        {
          filename: 'missing-size.txt',
          path: '/tmp/missing-size.txt',
          file_type: 'txt',
        },
        null,
      ],
    }))).toEqual([{
      filename: 'a.txt',
      path: '/tmp/a.txt',
      file_type: 'txt',
      file_size: 12,
    }]);
    expect(conversationAttachments(message({ attached_files: 'invalid' }))).toEqual([]);
  });

  it('parses thinking tags split across token boundaries', () => {
    let state = initialConversationStreamState();
    for (const event of [
      token(0, 'Answer <thi'),
      token(1, 'nk>private'),
      token(2, ' reasoning</thi'),
      token(3, 'nk> done', true),
    ]) {
      const reduction = reduceConversationToken(state, event);
      expect(reduction.accepted).toBe(true);
      state = reduction.state;
    }
    expect(state.content).toBe('Answer  done');
    expect(state.thinking).toBe('private reasoning');
    expect(state.buffer).toBe('');
    expect(state.insideThinking).toBe(false);
  });

  it('rejects duplicate, skipped, and out-of-order chunk IDs', () => {
    const first = reduceConversationToken(initialConversationStreamState(), token(0, 'one'));
    expect(first.accepted).toBe(true);
    expect(reduceConversationToken(first.state, token(0, 'duplicate')).accepted).toBe(false);
    expect(reduceConversationToken(first.state, token(2, 'skipped')).accepted).toBe(false);
    expect(reduceConversationToken(first.state, token(-1, 'older')).accepted).toBe(false);
    expect(first.state.content).toBe('one');
  });

  it('flushes an unterminated thinking section on the final token', () => {
    const first = reduceConversationToken(
      initialConversationStreamState(),
      token(0, '<think>unfinished'),
    );
    const final = reduceConversationToken(first.state, token(1, ' thought', true));
    expect(final.accepted).toBe(true);
    expect(final.state.content).toBe('');
    expect(final.state.thinking).toBe('unfinished thought');
    expect(final.state.insideThinking).toBe(false);
  });

  it('requires the pending request and rejects foreign conversations after adoption', () => {
    const matching: WSEvent = {
      event_type: 'conversation_token',
      request_id: 'request-1',
      conversation_id: 'conversation-1',
    };
    expect(acceptsConversationEvent(matching, undefined, 'request-1')).toBe(true);
    expect(acceptsConversationEvent(matching, 'conversation-1', 'request-1')).toBe(true);
    expect(acceptsConversationEvent(matching, 'conversation-2', 'request-1')).toBe(false);
    expect(acceptsConversationEvent(matching, undefined, 'request-2')).toBe(false);
    expect(acceptsConversationEvent({ ...matching, conversation_id: undefined }, undefined, 'request-1')).toBe(false);
  });

  it('accepts a persisted token or reset only for a known placeholder in the displayed conversation', () => {
    const knownIds = new Set(['assistant-1']);
    const persistedToken: WSEvent = {
      event_type: 'conversation_token',
      conversation_id: 'conversation-1',
      message_id: 'assistant-1',
    };
    expect(acceptsPersistedConversationEvent(persistedToken, 'conversation-1', knownIds)).toBe(true);
    expect(acceptsPersistedConversationEvent(
      { ...persistedToken, conversation_id: 'conversation-2' },
      'conversation-1',
      knownIds,
    )).toBe(false);
    expect(acceptsPersistedConversationEvent(
      { ...persistedToken, message_id: 'assistant-unknown' },
      'conversation-1',
      knownIds,
    )).toBe(false);
    expect(acceptsPersistedConversationEvent(
      { ...persistedToken, request_id: 'request-1' },
      'conversation-1',
      knownIds,
    )).toBe(false);
    expect(acceptsPersistedConversationEvent(
      { ...persistedToken, event_type: 'conversation_message' },
      'conversation-1',
      knownIds,
    )).toBe(false);
    expect(acceptsPersistedConversationEvent(
      { ...persistedToken, event_type: 'conversation_stream_reset' },
      'conversation-1',
      knownIds,
    )).toBe(true);
  });

  it('formats valid timestamps with the device locale and preserves malformed values', () => {
    const format = vi.fn().mockReturnValue('Jul 30, 2026, 8:00 AM');
    class MockDateTimeFormat {
      format = format;
    }
    const dateTimeFormat = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      MockDateTimeFormat as unknown as typeof Intl.DateTimeFormat,
    );

    expect(formatConversationTimestamp('2026-07-30T12:00:00Z')).toBe('Jul 30, 2026, 8:00 AM');
    expect(dateTimeFormat).toHaveBeenCalledWith(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
    expect(format).toHaveBeenCalledWith(new Date('2026-07-30T12:00:00Z'));
    expect(formatConversationTimestamp('not-a-date')).toBe('not-a-date');

    dateTimeFormat.mockRestore();
  });
});
