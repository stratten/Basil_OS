import { useEffect, useRef } from 'react';
import { HOME_CHAT_HANDOFF_MAX_AGE_MS, type HomeChatHandoff } from '../home/HomeForwardContext';
import type { ConversationDraftSubmission } from './conversationSessionState';

interface UseHomeChatHandoffOptions {
  handoff?: HomeChatHandoff;
  onConsumed?: (nonce: string) => void;
  connectionOpen: boolean;
  adoptConversation: (conversationId: string) => void;
  sendFirstMessage: (submission: ConversationDraftSubmission, conversationId: string) => boolean;
}

function createLocalId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}-${uuid}` : `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Home routes a request to Chats by creating the conversation on the backend
 * and handing the first message to this tab, which sends it over the same
 * streaming socket as any typed message. The handoff is consumed exactly once
 * and only after the socket is open; one that has gone stale (for example the
 * tab was unavailable) is dropped rather than sent later without context.
 */
export function useHomeChatHandoff({
  handoff,
  onConsumed,
  connectionOpen,
  adoptConversation,
  sendFirstMessage,
}: UseHomeChatHandoffOptions): void {
  const consumedNonce = useRef<string>();

  useEffect(() => {
    if (!handoff || consumedNonce.current === handoff.nonce) return;
    if (Date.now() - handoff.createdAt > HOME_CHAT_HANDOFF_MAX_AGE_MS) {
      consumedNonce.current = handoff.nonce;
      onConsumed?.(handoff.nonce);
      return;
    }
    if (!connectionOpen) return;
    consumedNonce.current = handoff.nonce;
    adoptConversation(handoff.conversationId);
    sendFirstMessage(
      {
        requestId: createLocalId('request'),
        messageId: createLocalId('message'),
        content: handoff.content,
        displayMarkdown: handoff.displayMarkdown,
        conversationId: handoff.conversationId,
        modelId: handoff.modelId,
        filePaths: handoff.filePaths,
        delegationOptOut: true,
        source: 'composer',
        editorHtml: '',
      },
      handoff.conversationId,
    );
    onConsumed?.(handoff.nonce);
  }, [adoptConversation, connectionOpen, handoff, onConsumed, sendFirstMessage]);
}
