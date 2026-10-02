import CollapsibleSidebar from '@shared/CollapsibleSidebar';
import { useHistoryRowRevealDelete } from '@shared/useHistoryRowRevealDelete';
import type { AssistantOutputHistoryEntry } from '../../services/historyApi';
import { formatSidebarTimestamp } from '../../lib/historyTimestamps';
import { NativeSymbol } from '../NativeSymbol';

export type HistoryModalityFilter = 'all' | 'voice' | 'text';

export function HistorySidebar({
  entries,
  selectedId,
  onSelect,
  collapsed,
  onToggleCollapsed,
  filter,
  onFilterChange,
  query,
  onQueryChange,
  onDelete,
  loadState,
  errorMessage,
  onRetry,
  refreshing,
  actionError,
  onDismissActionError,
}: {
  entries: AssistantOutputHistoryEntry[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  filter: HistoryModalityFilter;
  onFilterChange: (filter: HistoryModalityFilter) => void;
  query: string;
  onQueryChange: (query: string) => void;
  onDelete: (entry: AssistantOutputHistoryEntry) => void;
  loadState: 'loading' | 'ready' | 'error';
  errorMessage: string | null;
  onRetry: () => void;
  refreshing: boolean;
  actionError: string | null;
  onDismissActionError: () => void;
}) {
  return (
    <CollapsibleSidebar
      element="div"
      expanded={!collapsed}
      className="assistant-output-history-sidebar"
      collapsedContent={(
        <div className="assistant-output-history-sidebar__rail">
          <button type="button" title="Show AssistantSession history" aria-label="Show AssistantSession history" onClick={onToggleCollapsed}>
            <NativeSymbol name="sidebar" size={14} />
          </button>
        </div>
      )}
    >
      <div className="assistant-output-history-sidebar__header">
        <span>History</span>
        <button type="button" title="Hide history" onClick={onToggleCollapsed}>
          <NativeSymbol name="sidebar" size={12} />
        </button>
      </div>
      <div className="assistant-output-history-sidebar__filters">
        {(['all', 'voice', 'text'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={`assistant-output-history-sidebar__pill${filter === value ? ' assistant-output-history-sidebar__pill--active' : ''}`}
            onClick={() => onFilterChange(value)}
          >
            {value === 'all' ? 'All' : value === 'voice' ? 'Voice' : 'Text'}
          </button>
        ))}
      </div>
      <div className="assistant-output-history-sidebar__search-wrap">
        <NativeSymbol name="search" size={11} />
        <input
          className="assistant-output-history-sidebar__search"
          placeholder="Search AssistantSession history..."
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        {query && (
          <button type="button" className="assistant-output-history-sidebar__search-clear" onClick={() => onQueryChange('')}>
            <NativeSymbol name="cancel" size={11} />
          </button>
        )}
      </div>
      <div className="assistant-output-history-sidebar__list basil-refresh-region" aria-busy={refreshing && loadState === 'ready' ? true : undefined}>
        {actionError && (
          <div className="assistant-output-history-sidebar__status" role="alert">
            <p>{actionError}</p>
            <button type="button" onClick={onDismissActionError}>Dismiss</button>
          </div>
        )}
        {loadState === 'loading' && <div className="assistant-output-history-sidebar__status">Loading...</div>}
        {loadState === 'error' && (
          <div className="assistant-output-history-sidebar__status">
            <p>{errorMessage}</p>
            <button type="button" onClick={onRetry}>Retry</button>
          </div>
        )}
        {loadState === 'ready' && entries.length === 0 && (
          <div className="assistant-output-history-sidebar__status">No AssistantSession outputs yet</div>
        )}
        {loadState === 'ready' &&
          entries.map((entry) => (
            <HistorySidebarRow
              key={entry.id}
              entry={entry}
              isSelected={entry.id === selectedId}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          ))}
      </div>
    </CollapsibleSidebar>
  );
}

function HistorySidebarRow({
  entry,
  isSelected,
  onSelect,
  onDelete,
}: {
  entry: AssistantOutputHistoryEntry;
  isSelected: boolean;
  onSelect: (id: number) => void;
  onDelete: (entry: AssistantOutputHistoryEntry) => void;
}) {
  const title = entry.title || 'Untitled AssistantSession Output';
  const revealDelete = useHistoryRowRevealDelete({ enabled: true });

  const requestDelete = () => {
    revealDelete.close();
    onDelete(entry);
  };

  const select = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    onSelect(entry.id);
  };

  return (
    <div
      className={`assistant-output-history-sidebar__row${isSelected ? ' assistant-output-history-sidebar__row--active' : ''}`}
      onWheel={revealDelete.handleWheel}
    >
      {revealDelete.isOpen && (
        <button type="button" className="assistant-output-history-sidebar__swipe-delete" onClick={requestDelete}>
          Delete
        </button>
      )}
      <div
        className="assistant-output-history-sidebar__row-content"
        style={{ transform: revealDelete.offset > 0 ? `translateX(-${revealDelete.offset}px)` : undefined }}
      >
        <button type="button" className="assistant-output-history-sidebar__row-main" onClick={select}>
          <div className="assistant-output-history-sidebar__row-title">{title}</div>
          <div className="assistant-output-history-sidebar__row-preview">{entry.outputPreview}</div>
          <div className="assistant-output-history-sidebar__row-date">{formatSidebarTimestamp(entry.timestamp)}</div>
        </button>
        <button
          type="button"
          className="assistant-output-history-sidebar__delete"
          aria-label={`Delete ${title}`}
          title={`Delete ${title}`}
          onClick={requestDelete}
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M3.25 4.25h7.5M5.25 4.25V2.75h3.5v1.5M4.25 4.25l.5 7h4.5l.5-7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
