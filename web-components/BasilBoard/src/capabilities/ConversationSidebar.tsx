import { memo, useRef } from 'react';
import type { ConversationListItem } from '../contracts';
import { OpenInSeparateWindowIcon, StatusIcon, TrashIcon } from '@agent-task/components/sidebar/SidebarIcons';
import { CollapsedHistoryRail, HistorySearchField, HistorySidebarHeader } from '../../../shared/HistorySidebarControls';
import { useHistoryRowRevealDelete } from '../../../shared/useHistoryRowRevealDelete';
import CollapsibleSidebar from '../../../shared/CollapsibleSidebar';
import { openConversationThreadWindow } from '../services/bridge';
import { formatConversationTimestamp } from './chatsPresentation';
import { useConversationListMotion } from './useConversationListMotion';
import { plainMarkdownText } from '@shared/plainMarkdownText';

interface ConversationSidebarProps {
  conversations: ConversationListItem[];
  selectedId?: string;
  query: string;
  activeConversationIds: ReadonlySet<string>;
  loading: boolean;
  loadingMore: boolean;
  loadError?: string;
  loadMoreError?: string;
  hasMore: boolean;
  confirmingDeleteId?: string;
  deletingId?: string;
  deleteError?: string;
  isCollapsed: boolean;
  onQueryChange: (query: string) => void;
  onRetryLoad: () => void;
  onRetryLoadMore: () => void;
  onLoadMore: () => void;
  onStartNew: () => void;
  onCollapsedChange: (isCollapsed: boolean) => void;
  onSelect: (conversationId: string) => void;
  onRequestDelete: (conversationId: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (conversationId: string) => void;
}

function ConversationSidebarComponent({
  conversations,
  selectedId,
  query,
  activeConversationIds,
  loading,
  loadingMore,
  loadError,
  loadMoreError,
  hasMore,
  confirmingDeleteId,
  deletingId,
  deleteError,
  isCollapsed,
  onQueryChange,
  onRetryLoad,
  onRetryLoadMore,
  onLoadMore,
  onStartNew,
  onCollapsedChange,
  onSelect,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: ConversationSidebarProps) {
  const listRef = useRef<HTMLUListElement>(null);
  useConversationListMotion(listRef, conversations);
  return (
    <CollapsibleSidebar
      expanded={!isCollapsed}
      className={isCollapsed ? 'chats-sidebar chats-sidebar-collapsed' : 'chats-sidebar'}
      ariaLabel="Conversation history"
      collapsedContent={<CollapsedHistoryRail ariaLabel="Show conversation history" title="Show conversation history" onExpand={() => onCollapsedChange(false)} classNames={{ button: 'chats-sidebar-expand-button', symbol: 'chats-native-symbol chats-native-symbol-sidebar-expand' }} />}
    >
      <HistorySidebarHeader title="History" onStartNew={onStartNew} onCollapse={() => onCollapsedChange(true)} startLabel="Start new conversation" collapseLabel="Hide conversation history" classNames={{ root: 'chats-sidebar-header', actions: 'chats-sidebar-header-actions', button: 'chats-icon-button', symbol: 'chats-native-symbol chats-native-symbol-header' }} />
      <HistorySearchField value={query} onChange={onQueryChange} placeholder="Search conversations..." ariaLabel="Search conversations" classNames={{ root: 'chats-search', icon: 'chats-search-icon' }} />

      {loading && conversations.length === 0 ? (
        <div className="chats-sidebar-state" role="status">Loading conversations...</div>
      ) : loadError ? (
        <div className="chats-sidebar-state chats-error" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={onRetryLoad}>Retry</button>
        </div>
      ) : conversations.length === 0 ? (
        <div className="chats-sidebar-state">No conversations yet</div>
      ) : (
        <>
          <ul className="chats-conversation-list basil-refresh-region" ref={listRef} aria-busy={loading ? true : undefined}>
            {conversations.map((conversation) => (
              <ConversationHistoryRow
                key={conversation.id}
                conversation={conversation}
                isSelected={selectedId === conversation.id}
                isDeleteDisabled={activeConversationIds.has(conversation.id) || conversation.agent_status?.is_active === true}
                isConfirmingDelete={confirmingDeleteId === conversation.id}
                isDeleting={deletingId === conversation.id}
                onSelect={onSelect}
                onRequestDelete={onRequestDelete}
                onCancelDelete={onCancelDelete}
                onConfirmDelete={onConfirmDelete}
              />
            ))}
          </ul>
          {loadMoreError ? (
            <div className="chats-load-more-error" role="alert">
              <span>{loadMoreError}</span>
              <button type="button" onClick={onRetryLoadMore}>Retry</button>
            </div>
          ) : null}
          {hasMore ? (
            <button
              type="button"
              className="chats-load-more-button"
              onClick={onLoadMore}
              disabled={loadingMore}
              aria-busy={loadingMore}
            >
              {loadingMore ? 'Loading more conversations...' : 'Load more conversations'}
            </button>
          ) : null}
        </>
      )}
      {deleteError ? <div className="chats-inline-error" role="alert">{deleteError}</div> : null}
    </CollapsibleSidebar>
  );
}

interface ConversationHistoryRowProps {
  conversation: ConversationListItem;
  isSelected: boolean;
  isDeleteDisabled: boolean;
  isConfirmingDelete: boolean;
  isDeleting: boolean;
  onSelect: (conversationId: string) => void;
  onRequestDelete: (conversationId: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (conversationId: string) => void;
}

function ConversationHistoryRowComponent({
  conversation,
  isSelected,
  isDeleteDisabled,
  isConfirmingDelete,
  isDeleting,
  onSelect,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: ConversationHistoryRowProps) {
  const displayTitle = plainMarkdownText(conversation.title) || 'New Conversation';
  const revealDelete = useHistoryRowRevealDelete({ enabled: !isDeleteDisabled });
  const requestDelete = () => {
    if (isDeleteDisabled) return;
    revealDelete.close();
    onRequestDelete(conversation.id);
  };
  const selectConversation = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    onSelect(conversation.id);
  };
  const openInSeparateWindow = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    openConversationThreadWindow(conversation.id);
  };

  return (
    <li onWheel={revealDelete.handleWheel} data-conversation-id={conversation.id}>
      {revealDelete.isOpen && (
        <button type="button" className="chats-swipe-delete-button" onClick={requestDelete}>Delete</button>
      )}
      <button
        type="button"
        className={`chats-conversation-row${isSelected ? ' is-active' : ''}`}
        style={{ transform: revealDelete.offset > 0 ? `translateX(-${revealDelete.offset}px)` : undefined }}
        onClick={selectConversation}
        onDoubleClick={openInSeparateWindow}
      >
        <span className="chats-conversation-title">
          <span className="chats-conversation-title-text">{displayTitle}</span>
          {conversation.agent_status && (
            <span
              className="chats-conversation-agent-status"
              title={`Agent Task ${conversation.agent_status.is_active ? 'in progress' : conversation.agent_status.status}`}
            >
              <StatusIcon
                status={conversation.agent_status.status}
                resultSeverity={conversation.agent_status.result_severity ?? undefined}
                size={8}
              />
            </span>
          )}
        </span>
        {conversation.last_message_preview ? (
          <span className="chats-conversation-preview">
            {conversation.last_message_preview}
          </span>
        ) : null}
        <span className="chats-conversation-meta">
          <span>{formatConversationTimestamp(conversation.updated_at)}</span>
          <span>{conversation.message_count} msg</span>
        </span>
      </button>
      <div className="chats-conversation-row-actions">
        <button
          type="button"
          className="chats-delete-button"
          onClick={(event) => {
            event.stopPropagation();
            requestDelete();
          }}
          onDoubleClick={(event) => event.stopPropagation()}
          disabled={isDeleteDisabled}
          aria-label={`Delete ${displayTitle}`}
          title={`Delete ${displayTitle}`}
        >
          <TrashIcon size={10} />
        </button>
        <button
          type="button"
          className="chats-open-conversation-button"
          onClick={(event) => {
            event.stopPropagation();
            openConversationThreadWindow(conversation.id);
          }}
          onDoubleClick={(event) => event.stopPropagation()}
          aria-label={`Open ${displayTitle} in a separate window`}
          title="Open in separate window"
        >
          <OpenInSeparateWindowIcon size={10} />
        </button>
      </div>
      {isConfirmingDelete ? (
        <div
          className="chats-delete-confirmation"
          role="alertdialog"
          aria-label="Delete conversation"
        >
          <span>Delete this conversation?</span>
          <button type="button" onClick={onCancelDelete}>Cancel</button>
          <button
            type="button"
            onClick={() => onConfirmDelete(conversation.id)}
            disabled={isDeleting}
          >
            {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      ) : null}
    </li>
  );
}

const ConversationHistoryRow = memo(ConversationHistoryRowComponent);

export default memo(ConversationSidebarComponent);
