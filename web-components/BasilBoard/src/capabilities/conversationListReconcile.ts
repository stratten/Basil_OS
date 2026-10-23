import type { ConversationListItem } from '../contracts';

function sameConversationSummary(current: ConversationListItem, incoming: ConversationListItem): boolean {
  return current.id === incoming.id
    && current.title === incoming.title
    && current.created_at === incoming.created_at
    && current.updated_at === incoming.updated_at
    && current.message_count === incoming.message_count
    && current.last_message_preview === incoming.last_message_preview
    && JSON.stringify(current.agent_status ?? null) === JSON.stringify(incoming.agent_status ?? null);
}

/**
 * Merges a freshly fetched first page into the visible list. Unchanged rows keep their object identity so memoized rows do not re-render, and rows loaded from later pages are kept while the first page reports more results. The server orders pages by `updated_at` descending.
 */
export function reconcileConversationFirstPage(
  current: readonly ConversationListItem[],
  firstPage: readonly ConversationListItem[],
  firstPageHasMore: boolean,
): ConversationListItem[] {
  const currentById = new Map(current.map((conversation) => [conversation.id, conversation]));
  const reconciledPage = firstPage.map((incoming) => {
    const existing = currentById.get(incoming.id);
    return existing && sameConversationSummary(existing, incoming) ? existing : incoming;
  });
  let next = reconciledPage;
  if (firstPageHasMore && firstPage.length > 0) {
    const pageIds = new Set(firstPage.map((conversation) => conversation.id));
    const oldestUpdatedAtOnPage = firstPage[firstPage.length - 1].updated_at;
    const laterPages = current.filter((conversation) => (
      !pageIds.has(conversation.id) && conversation.updated_at <= oldestUpdatedAtOnPage
    ));
    next = [...reconciledPage, ...laterPages];
  }
  const unchanged = next.length === current.length && next.every((conversation, index) => conversation === current[index]);
  return unchanged ? current as ConversationListItem[] : next;
}
