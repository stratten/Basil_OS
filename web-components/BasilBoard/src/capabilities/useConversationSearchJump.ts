import { useCallback, useEffect, useRef, useState, type MutableRefObject, type RefObject } from 'react';
import { clearSearchFocus, publishSearchFocus } from '@shared/search/searchFocusStore';
import { scrollOffsetForElement } from '@shared/search/scrollOffset';
import { getConversationSearchMatches } from '../services/api';

function escapeAttributeValue(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(value);
  return value.replace(/["\\]/g, '\\$&');
}

interface PendingJump {
  token: number;
  conversationId: string;
  query: string;
  tokens: string[];
  matchedIds: string[];
}

interface UseConversationSearchJumpArgs {
  viewportRef: RefObject<HTMLElement | null>;
  /** The transcript's pin-to-bottom flag; a jump releases it so the transcript does not snap back to the end. */
  pinnedToBottomRef: MutableRefObject<boolean>;
  selectedConversationId: string | undefined;
  /** The text in the sidebar search box; emptying it drops the highlight. */
  query: string;
}

/**
 * Opens a conversation chosen from a sidebar search at the first message that contains the searched phrase, and
 * publishes the matches so `useSearchHighlight` can mark them.
 *
 * `begin` is called when a conversation is selected: it clears any earlier focus, then (only when the search box has
 * text) fetches the matching message ids best-effort. `historyLoaded` is called when that selection's history load has
 * finished. The jump runs only after both have happened and the messages are rendered, because the history load pins
 * the transcript to the bottom when it completes and the jump has to come after that. A title-only match (no message
 * contains the phrase), a failed lookup, or a stale click all leave the conversation open at the bottom as before.
 */
export function useConversationSearchJump({
  viewportRef,
  pinnedToBottomRef,
  selectedConversationId,
  query,
}: UseConversationSearchJumpArgs) {
  const [pending, setPending] = useState<PendingJump | null>(null);
  const [loadedToken, setLoadedToken] = useState(0);
  const tokenRef = useRef(0);

  const begin = useCallback((conversationId: string, searchText: string): number => {
    tokenRef.current += 1;
    const token = tokenRef.current;
    setPending(null);
    clearSearchFocus();
    const phrase = searchText.trim();
    if (!phrase) return token;
    void getConversationSearchMatches(conversationId, phrase)
      .then((matches) => {
        if (token !== tokenRef.current || matches.matched_message_ids.length === 0) return;
        setPending({
          token,
          conversationId,
          query: phrase,
          tokens: matches.tokens,
          matchedIds: matches.matched_message_ids,
        });
      })
      .catch((error: unknown) => {
        console.warn('[Chats] Search-match lookup failed; opening the conversation without a jump:', error);
      });
    return token;
  }, []);

  const historyLoaded = useCallback((token: number) => {
    if (token === tokenRef.current) setLoadedToken(token);
  }, []);

  const cancel = useCallback(() => {
    tokenRef.current += 1;
    setPending(null);
    clearSearchFocus();
  }, []);

  useEffect(() => {
    if (!query.trim()) cancel();
  }, [query, cancel]);

  useEffect(() => () => {
    tokenRef.current += 1;
    clearSearchFocus();
  }, []);

  useEffect(() => {
    if (!pending || pending.token !== loadedToken || pending.conversationId !== selectedConversationId) return;
    const viewport = viewportRef.current;
    if (!viewport) return;
    const target = pending.matchedIds
      .map((id) => viewport.querySelector<HTMLElement>(`[data-message-id="${escapeAttributeValue(id)}"]`))
      .find((element): element is HTMLElement => element !== null);
    if (target) {
      pinnedToBottomRef.current = false;
      viewport.scrollTop = scrollOffsetForElement(viewport, target);
    }
    publishSearchFocus({
      scopeId: pending.conversationId,
      query: pending.query,
      tokens: pending.tokens,
      matchedIds: pending.matchedIds,
    });
    setPending(null);
  }, [pending, loadedToken, selectedConversationId, viewportRef, pinnedToBottomRef]);

  return { begin, historyLoaded, cancel };
}
