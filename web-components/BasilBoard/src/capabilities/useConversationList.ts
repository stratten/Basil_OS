import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AgentOriginStatusSummary, ConversationListItem } from '../contracts';
import { getConversationAgentStatuses, listConversationPage } from '../services/api';
import { basilBoardWebSocket } from '../services/websocket';
import { reconcileConversationFirstPage } from './conversationListReconcile';

const CONVERSATION_PAGE_SIZE = 30;

function mergeConversationPages(
  current: ConversationListItem[],
  next: ConversationListItem[],
): ConversationListItem[] {
  const knownIds = new Set(current.map((conversation) => conversation.id));
  return [...current, ...next.filter((conversation) => !knownIds.has(conversation.id))];
}

export function useConversationList() {
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  const [loadMoreError, setLoadMoreError] = useState<string>();
  const [hasMore, setHasMore] = useState(false);
  const nextCursorRef = useRef<string>();
  const requestVersionRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const loadingRef = useRef(true);
  const conversationsRef = useRef<ConversationListItem[]>([]);
  conversationsRef.current = conversations;

  const loadFirstPage = useCallback(async (requestedQuery: string) => {
    const version = ++requestVersionRef.current;
    const normalizedQuery = requestedQuery.trim();
    nextCursorRef.current = undefined;
    loadingMoreRef.current = false;
    loadingRef.current = true;
    setHasMore(false);
    setLoading(true);
    setLoadingMore(false);
    setLoadError(undefined);
    setLoadMoreError(undefined);
    try {
      const page = await listConversationPage({
        query: normalizedQuery || undefined,
        limit: CONVERSATION_PAGE_SIZE,
      });
      if (version !== requestVersionRef.current) return;
      setConversations(page.conversations);
      setHasMore(page.has_more);
      nextCursorRef.current = page.next_cursor ?? undefined;
    } catch (error) {
      if (version !== requestVersionRef.current) return;
      setLoadError(error instanceof Error ? error.message : 'Failed to load conversations');
    } finally {
      if (version === requestVersionRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, []);

  const onQueryChange = useCallback((nextQuery: string) => {
    requestVersionRef.current += 1;
    nextCursorRef.current = undefined;
    loadingMoreRef.current = false;
    setQuery(nextQuery);
    setHasMore(false);
    setLoadingMore(false);
    setLoadError(undefined);
    setLoadMoreError(undefined);
  }, []);

  const reload = useCallback(() => {
    void loadFirstPage(query);
  }, [loadFirstPage, query]);

  const refresh = useCallback(async () => {
    if (loadingRef.current) return;
    const version = requestVersionRef.current;
    const normalizedQuery = query.trim();
    try {
      const page = await listConversationPage({
        query: normalizedQuery || undefined,
        limit: CONVERSATION_PAGE_SIZE,
      });
      if (version !== requestVersionRef.current) return;
      const listExtendsPastFirstPage = page.has_more
        && conversationsRef.current.length > page.conversations.length;
      setConversations((current) => reconcileConversationFirstPage(current, page.conversations, page.has_more));
      if (!listExtendsPastFirstPage) {
        setHasMore(page.has_more);
        nextCursorRef.current = page.next_cursor ?? undefined;
      }
      setLoadError(undefined);
    } catch {
      // A failed background refresh keeps the visible list; the next event or the Retry button reloads it.
    }
  }, [query]);

  const removeConversation = useCallback((conversationId: string) => {
    setConversations((current) => (
      current.some((conversation) => conversation.id === conversationId)
        ? current.filter((conversation) => conversation.id !== conversationId)
        : current
    ));
  }, []);

  const loadMore = useCallback(async () => {
    const cursor = nextCursorRef.current;
    if (!cursor || !hasMore || loadingMoreRef.current) return;
    const version = requestVersionRef.current;
    const normalizedQuery = query.trim();
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError(undefined);
    try {
      const page = await listConversationPage({
        query: normalizedQuery || undefined,
        cursor,
        limit: CONVERSATION_PAGE_SIZE,
      });
      if (version !== requestVersionRef.current) return;
      setConversations((current) => mergeConversationPages(current, page.conversations));
      setHasMore(page.has_more);
      nextCursorRef.current = page.next_cursor ?? undefined;
    } catch (error) {
      if (version !== requestVersionRef.current) return;
      setLoadMoreError(error instanceof Error ? error.message : 'Failed to load more conversations');
    } finally {
      if (version === requestVersionRef.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [hasMore, query]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void loadFirstPage(query);
    }, query.trim() ? 300 : 0);
    return () => window.clearTimeout(handle);
  }, [loadFirstPage, query]);

  const [liveAgentStatuses, setLiveAgentStatuses] = useState<Record<string, AgentOriginStatusSummary | null>>({});
  const conversationIdsKey = conversations.map((conversation) => conversation.id).sort().join(',');
  const agentStatusDebounceRef = useRef<number>();

  useEffect(() => {
    let canceled = false;
    const ids = conversationIdsKey ? conversationIdsKey.split(',') : [];

    const refreshAgentStatuses = () => {
      if (ids.length === 0) {
        setLiveAgentStatuses({});
        return;
      }
      void getConversationAgentStatuses(ids)
        .then((result) => {
          if (canceled) return;
          setLiveAgentStatuses(result as Record<string, AgentOriginStatusSummary | null>);
        })
        .catch(() => {
          // Keep the last-known statuses; a failed live refresh should not blank the UI.
        });
    };

    refreshAgentStatuses();

    const unsubscribe = basilBoardWebSocket.subscribe((event) => {
      if (typeof event.agent_task_id !== 'string') return;
      window.clearTimeout(agentStatusDebounceRef.current);
      agentStatusDebounceRef.current = window.setTimeout(refreshAgentStatuses, 300);
    });

    return () => {
      canceled = true;
      window.clearTimeout(agentStatusDebounceRef.current);
      unsubscribe();
    };
  }, [conversationIdsKey]);

  const liveStatusCacheRef = useRef(new WeakMap<ConversationListItem, { statusKey: string; merged: ConversationListItem }>());
  const conversationsWithLiveStatus = useMemo(() => conversations.map((conversation) => {
    if (!(conversation.id in liveAgentStatuses)) return conversation;
    const status = liveAgentStatuses[conversation.id];
    const statusKey = JSON.stringify(status ?? null);
    const cached = liveStatusCacheRef.current.get(conversation);
    if (cached && cached.statusKey === statusKey) return cached.merged;
    const merged = { ...conversation, agent_status: status };
    liveStatusCacheRef.current.set(conversation, { statusKey, merged });
    return merged;
  }), [conversations, liveAgentStatuses]);

  return {
    conversations: conversationsWithLiveStatus,
    query,
    loading,
    loadingMore,
    loadError,
    loadMoreError,
    hasMore,
    onQueryChange,
    reload,
    refresh,
    removeConversation,
    loadMore,
  };
}
