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
}) {
  if (collapsed) {
    return (
      <div className="assistant-output-history-sidebar assistant-output-history-sidebar--collapsed">
        <button type="button" title="Show AssistantSession history" onClick={onToggleCollapsed}>
          <NativeSymbol name="sidebar" size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className="assistant-output-history-sidebar">
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
      <div className="assistant-output-history-sidebar__list">
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
            <div
              key={entry.id}
              className={`assistant-output-history-sidebar__row${entry.id === selectedId ? ' assistant-output-history-sidebar__row--active' : ''}`}
            >
              <button type="button" className="assistant-output-history-sidebar__row-main" onClick={() => onSelect(entry.id)}>
                <div className="assistant-output-history-sidebar__row-title">{entry.title || 'Untitled AssistantSession Output'}</div>
                <div className="assistant-output-history-sidebar__row-preview">{entry.outputPreview}</div>
                <div className="assistant-output-history-sidebar__row-date">{formatSidebarTimestamp(entry.timestamp)}</div>
              </button>
              <button type="button" className="assistant-output-history-sidebar__delete" title="Delete" onClick={() => onDelete(entry)}>
                <NativeSymbol name="cancel" size={12} />
              </button>
            </div>
          ))}
      </div>
    </div>
  );
}
