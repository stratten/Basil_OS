import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HOME_CHAT_HANDOFF_MAX_AGE_MS, type HomeChatHandoff } from '../home/HomeForwardContext';
import { useHomeChatHandoff } from './useHomeChatHandoff';

function handoff(overrides: Partial<HomeChatHandoff> = {}): HomeChatHandoff {
  return {
    nonce: 'nonce-1',
    conversationId: 'conv-1',
    content: 'What changed in the Q3 plan?',
    displayMarkdown: 'What changed in the **Q3** plan?',
    filePaths: ['/tmp/q3.pdf'],
    modelId: 'model-a',
    createdAt: Date.now(),
    ...overrides,
  };
}

function setup(initial: { handoff?: HomeChatHandoff; connectionOpen: boolean }) {
  const onConsumed = vi.fn();
  const adoptConversation = vi.fn();
  const sendFirstMessage = vi.fn(() => true);
  const hook = renderHook((props: { handoff?: HomeChatHandoff; connectionOpen: boolean }) => useHomeChatHandoff({
    handoff: props.handoff,
    onConsumed,
    connectionOpen: props.connectionOpen,
    adoptConversation,
    sendFirstMessage,
  }), { initialProps: initial });
  return { ...hook, onConsumed, adoptConversation, sendFirstMessage };
}

describe('useHomeChatHandoff', () => {
  it('waits for the socket, then selects the conversation and sends the first message once', () => {
    const { rerender, onConsumed, adoptConversation, sendFirstMessage } = setup({
      handoff: handoff(),
      connectionOpen: false,
    });
    expect(sendFirstMessage).not.toHaveBeenCalled();

    rerender({ handoff: handoff(), connectionOpen: true });
    rerender({ handoff: handoff(), connectionOpen: true });

    expect(adoptConversation).toHaveBeenCalledWith('conv-1');
    expect(sendFirstMessage).toHaveBeenCalledTimes(1);
    const [submission, conversationId] = sendFirstMessage.mock.calls[0] as unknown as [Record<string, unknown>, string];
    expect(conversationId).toBe('conv-1');
    expect(submission).toMatchObject({
      content: 'What changed in the Q3 plan?',
      displayMarkdown: 'What changed in the **Q3** plan?',
      conversationId: 'conv-1',
      modelId: 'model-a',
      filePaths: ['/tmp/q3.pdf'],
      delegationOptOut: true,
      source: 'composer',
    });
    expect(onConsumed).toHaveBeenCalledWith('nonce-1');
  });

  it('drops a stale handoff instead of sending it later', () => {
    const { onConsumed, adoptConversation, sendFirstMessage } = setup({
      handoff: handoff({ createdAt: Date.now() - HOME_CHAT_HANDOFF_MAX_AGE_MS - 1 }),
      connectionOpen: true,
    });

    expect(sendFirstMessage).not.toHaveBeenCalled();
    expect(adoptConversation).not.toHaveBeenCalled();
    expect(onConsumed).toHaveBeenCalledWith('nonce-1');
  });

  it('does nothing without a handoff', () => {
    const { sendFirstMessage, onConsumed } = setup({ connectionOpen: true });

    expect(sendFirstMessage).not.toHaveBeenCalled();
    expect(onConsumed).not.toHaveBeenCalled();
  });
});
