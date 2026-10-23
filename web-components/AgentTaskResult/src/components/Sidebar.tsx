import { useState, useEffect, useRef, useCallback } from 'react';
import type { MouseEvent } from 'react';
import type {
  AgentTaskListItem,
  DisplayableAgentTask,
  ScheduledAgentTask,
} from '../types';
import { useAllAgents, useSelectAgent, agentStore } from '../store/agentStore';
import * as api from '../services/api';
import { openDetachedAgentTask, startNewAgentTaskCapture } from '../services/bridge';
import NativeSymbolIcon from '../../../shared/NativeSymbolIcon';
import { AgentTaskRow } from './sidebar/AgentTaskRow';
import type { AgentTaskRowProps } from './sidebar/AgentTaskRow';
import {
  ArchiveBoxIcon,
  CalendarIcon,
  MicrophoneIcon,
  OpenInSeparateWindowIcon,
  PlusCircleIcon,
  TrashIcon,
  WarningIcon,
} from './sidebar/SidebarIcons';
import { buildHistoryItems, buildScheduledItems, isActiveStatus } from './sidebar/sidebarItemBuilders';
import { usePendingFollowUps } from '../store/pendingFollowUps';
import { mapDetailToDisplayable } from './sidebar/sidebarUtils';

const HISTORY_PAGE_SIZE = 300;
const HISTORY_SEARCH_DEBOUNCE_MS = 300;

export function isLiveAgentTaskStatus(status: string): boolean {
  return ['capturing', 'routing', 'processing', 'awaiting_user_input', 'needs_clarification', 'paused'].includes(status);
}

function AgentTaskSidebarToggleIcon() {
  return <NativeSymbolIcon name="sidebar" className="sidebar-toggle-symbol" />;
}

// --- Main Sidebar Component ---

interface Props {
  isExpanded: boolean;
  canLoadData: boolean;
  onToggle: () => void;
  onViewHistoricalAgentTask: (detail: DisplayableAgentTask) => void;
  onViewAgentTask: (agentTaskId: string) => void;
  onViewScheduledAgentTask: (scheduledAgentTaskId: string) => void;
  onCreateScheduledAgentTask: () => void;
  selectedScheduledAgentTaskId?: string | null;
  // Monotonically-increasing counter bumped by the parent whenever the set of
  // scheduled agent tasks changes outside of this component (e.g. a new schedule
  // is persisted via the create form). When this value changes we re-fetch
  // the scheduled list so the newly-created row shows up — and, combined
  // with `selectedScheduledAgentTaskId`, highlights as selected — without the
  // user having to toggle views to force a refresh.
  scheduledListVersion?: number;
  viewedAgentTaskId?: string | null;
  viewedRootId?: string | null;
  onAgentTaskDeleted?: (agentTaskId: string) => void;
  // Root task ids open in a detached window; their rows suppress the
  // approval/awaiting signal since the pop-out owns the interactive surface.
  detachedRootsElsewhere?: Set<string>;
}

export default function Sidebar({
  isExpanded,
  canLoadData,
  onToggle,
  onViewHistoricalAgentTask,
  onViewAgentTask,
  onViewScheduledAgentTask,
  onCreateScheduledAgentTask,
  selectedScheduledAgentTaskId,
  scheduledListVersion,
  viewedAgentTaskId,
  viewedRootId,
  onAgentTaskDeleted,
  detachedRootsElsewhere,
}: Props) {
  const allAgents = useAllAgents();
  const selectAgent = useSelectAgent();
  const selectedId = agentStore.getSelectedAgentId();

  const [history, setHistory] = useState<AgentTaskListItem[]>([]);
  const [loadedHistory, setLoadedHistory] = useState<AgentTaskListItem[]>([]);
  const [scheduled, setScheduled] = useState<ScheduledAgentTask[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyDeepSearching, setHistoryDeepSearching] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'history' | 'scheduled' | 'archived'>('history');
  const [searchQuery, setSearchQuery] = useState('');
  // Root ids archived during this session. buildHistoryItems merges live store agents into the Tasks list unconditionally, so these are filtered out of it until the chain becomes active again.
  const [sessionArchivedRootIds, setSessionArchivedRootIds] = useState<Set<string>>(() => new Set());
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const historyRequestSeqRef = useRef(0);

  // Id of the history row currently showing its inline "Delete this
  // AgentTask?" confirmation in place of its normal content (see
  // AgentTaskRow's isPendingDelete prop). Only one row confirms at a time.
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    item: AgentTaskListItem;
    rootTaskId?: string;
    canDelete?: boolean;
    canArchive?: boolean;
  } | null>(null);

  const activeIds = new Set(allAgents.map(a => a.agentTaskId));

  const loadHistory = useCallback(async () => {
    if (!canLoadData || !api.isApiReady()) return;

    const requestSeq = ++historyRequestSeqRef.current;
    const isArchivedView = viewMode === 'archived';
    // The Archived view lists only backend results; live store agents never merge into it.
    const filterVisibleHistory = (agentTasks: AgentTaskListItem[]) =>
      isArchivedView ? agentTasks : agentTasks.filter(c => !activeIds.has(c.id));

    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await api.listAgentTasks(HISTORY_PAGE_SIZE, 0, undefined, { archived: isArchivedView });
      if (requestSeq !== historyRequestSeqRef.current) return;

      const visibleAgentTasks = filterVisibleHistory(result.agentTasks);
      setLoadedHistory(visibleAgentTasks);
      setHistory(visibleAgentTasks);
    } catch (err) {
      if (requestSeq !== historyRequestSeqRef.current) return;
      setHistoryError('Failed to load history');
      console.error('[Sidebar] History load error:', err);
    } finally {
      if (requestSeq === historyRequestSeqRef.current) {
        setHistoryLoading(false);
      }
    }
  }, [activeIds, canLoadData, viewMode]);

  const loadScheduled = useCallback(async () => {
    if (!canLoadData || !api.isApiReady()) return;

    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const result = await api.listScheduledAgentTasks(true);
      setScheduled(result.agent_tasks);
    } catch (err) {
      setHistoryError('Failed to load scheduled tasks');
      console.error('[Sidebar] Scheduled load error:', err);
    } finally {
      setHistoryLoading(false);
    }
  }, [canLoadData]);

  useEffect(() => {
    if (!isExpanded) return;
    if (!canLoadData) return;
    if (viewMode === 'scheduled') {
      loadScheduled();
    } else {
      loadHistory();
    }
  }, [isExpanded, viewMode, canLoadData]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refresh the scheduled list whenever the parent signals that it changed
  // (e.g. a schedule was just created). We refresh regardless of current
  // view mode so the list is already warm if/when the user toggles to it;
  // when the user is already on the scheduled view, this makes the newly-
  // created row appear — and select — immediately without a view toggle.
  // Guarded on `scheduledListVersion` being defined so the initial mount
  // doesn't double-fetch alongside the view-mode effect above.
  useEffect(() => {
    if (!isExpanded) return;
    if (!canLoadData) return;
    if (scheduledListVersion === undefined) return;
    loadScheduled();
  }, [scheduledListVersion, isExpanded, canLoadData]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [contextMenu]);

  const locallyFilterHistory = (items: AgentTaskListItem[], value: string) => {
    const lowered = value.trim().toLowerCase();
    if (!lowered) return items;
    return items.filter(item => {
      const haystack = [
        item.title,
        item.original_prompt,
        item.result_preview,
        item.app_name,
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(lowered);
    });
  };

  const handleSearch = (value: string) => {
    const trimmed = value.trim();
    const requestSeq = ++historyRequestSeqRef.current;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    setHistory(locallyFilterHistory(loadedHistory, value));

    if (!trimmed) {
      setHistoryDeepSearching(false);
      return;
    }

    searchTimerRef.current = setTimeout(() => {
      setHistoryDeepSearching(true);
      const isArchivedView = viewMode === 'archived';
      api.searchAgentTasks(trimmed, HISTORY_PAGE_SIZE, 0, { archived: isArchivedView })
        .then(result => {
          if (requestSeq !== historyRequestSeqRef.current) return;
          setHistory(isArchivedView ? result.agentTasks : result.agentTasks.filter(c => !activeIds.has(c.id)));
        })
        .catch(err => {
          if (requestSeq === historyRequestSeqRef.current) {
            console.error('[Sidebar] Deep history search error:', err);
          }
        })
        .finally(() => {
          if (requestSeq === historyRequestSeqRef.current) {
            setHistoryDeepSearching(false);
          }
        });
    }, HISTORY_SEARCH_DEBOUNCE_MS);
  };

  const handleSelectHistory = useCallback(async (item: AgentTaskListItem) => {
    if (isLiveAgentTaskStatus(item.status)) {
      onViewAgentTask(item.id);
      return;
    }

    try {
      const detail = await api.getAgentTaskDetail(item.id);
      const displayable = mapDetailToDisplayable(detail);
      onViewHistoricalAgentTask(displayable);
    } catch (err) {
      console.error('[Sidebar] Failed to load AgentTask detail:', err);
    }
  }, [onViewAgentTask, onViewHistoricalAgentTask]);

  const handleSelectHistoryId = useCallback((id: string) => {
    const item = history.find(historyItem => historyItem.id === id);
    if (item) void handleSelectHistory(item);
  }, [handleSelectHistory, history]);

  const switchViewMode = (next: 'history' | 'scheduled' | 'archived') => {
    if (next === viewMode) return;
    // Invalidate any in-flight list or search so a slow response cannot repopulate the previous view.
    historyRequestSeqRef.current += 1;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    setSearchQuery('');
    setHistoryDeepSearching(false);
    setHistoryError(null);
    setHistory([]);
    setLoadedHistory([]);
    setContextMenu(null);
    setViewMode(next);
  };

  const handleNewAgent = () => {
    if (viewMode === 'scheduled') {
      onCreateScheduledAgentTask();
      return;
    }
    const preId = crypto.randomUUID();
    startNewAgentTaskCapture(preId);
  };

  const requestDelete = useCallback((id: string) => {
    setPendingDeleteId(id);
    setContextMenu(null);
  }, []);

  const itemForAgentId = useCallback((id: string): AgentTaskListItem | undefined => {
    const agent = agentStore.getAgent(id);
    if (agent) {
      return {
        id: agent.agentTaskId,
        original_prompt: agent.originalPrompt || '',
        title: agent.originalPrompt || undefined,
        timestamp: agent.timestamp || new Date().toISOString(),
        status: agent.status,
        result_severity: agent.resultSeverity,
        result_preview: '',
        file_count: 0,
        follow_up_count: 0,
      };
    }
    return history.find(historyItem => historyItem.id === id);
  }, [history]);

  const detachAgentTaskById = useCallback((id: string) => {
    const agent = agentStore.getAgent(id);
    openDetachedAgentTask(agent?.rootTaskId || id);
  }, []);

  const openContextMenuForId = useCallback((event: MouseEvent, id: string) => {
    event.preventDefault();
    event.stopPropagation();
    const item = itemForAgentId(id);
    if (!item) return;
    const agent = agentStore.getAgent(id);
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      item,
      rootTaskId: agent?.rootTaskId,
      canDelete: agent ? !isActiveStatus(agent.status) : true,
      canArchive: agent ? !isActiveStatus(agent.status) : !isLiveAgentTaskStatus(item.status),
    });
  }, [itemForAgentId]);

  const cancelAgentTask = useCallback(async (agentTaskId: string) => {
    agentStore.markCanceling(agentTaskId);
    try {
      await api.cancelSession(agentTaskId);
    } catch (err) {
      console.error('[Sidebar] Cancel failed:', err);
    }
  }, []);

  const confirmDelete = useCallback(async (id: string) => {
    try {
      await api.deleteAgentTask(id);
      setHistory(prev => prev.filter(h => h.id !== id));
      agentStore.removeAgent(id);
      onAgentTaskDeleted?.(id);
    } catch (err) {
      console.error('[Sidebar] Delete failed:', err);
    } finally {
      setPendingDeleteId(null);
    }
  }, [onAgentTaskDeleted]);

  const cancelDelete = useCallback(() => {
    setPendingDeleteId(null);
  }, []);

  const archiveChain = useCallback(async (id: string) => {
    const rootId = agentStore.getAgent(id)?.rootTaskId || id;
    try {
      await api.archiveAgentTask(id);
      setHistory(prev => prev.filter(h => h.id !== id && h.id !== rootId));
      setLoadedHistory(prev => prev.filter(h => h.id !== id && h.id !== rootId));
      setSessionArchivedRootIds(prev => new Set(prev).add(rootId));
      setContextMenu(null);
    } catch (err) {
      console.error('[Sidebar] Archive failed:', err);
    }
  }, []);

  const unarchiveChain = useCallback(async (id: string) => {
    try {
      await api.unarchiveAgentTask(id);
      setHistory(prev => prev.filter(h => h.id !== id));
      setLoadedHistory(prev => prev.filter(h => h.id !== id));
      setSessionArchivedRootIds(prev => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setContextMenu(null);
    } catch (err) {
      console.error('[Sidebar] Unarchive failed:', err);
    }
  }, []);

  // A chain archived this session returns to Tasks the moment its agent becomes active again (for example a follow-up submitted from an open detail view).
  useEffect(() => {
    if (sessionArchivedRootIds.size === 0) return;
    const reactivated = allAgents.filter(agent =>
      isActiveStatus(agent.status) && sessionArchivedRootIds.has(agent.rootTaskId || agent.agentTaskId));
    if (reactivated.length === 0) return;
    setSessionArchivedRootIds(prev => {
      const next = new Set(prev);
      reactivated.forEach(agent => next.delete(agent.rootTaskId || agent.agentTaskId));
      return next;
    });
  }, [allAgents, sessionArchivedRootIds]);

  const isSearchActive = searchQuery.trim().length > 0;
  const pendingFollowUps = usePendingFollowUps();

  const isArchivedView = viewMode === 'archived';
  const visibleAgents = isArchivedView
    ? []
    : allAgents.filter(agent => !sessionArchivedRootIds.has(agent.rootTaskId || agent.agentTaskId));

  const historyItems: AgentTaskRowProps[] = buildHistoryItems({
    allAgents: visibleAgents,
    history,
    activeIds: isArchivedView ? new Set<string>() : activeIds,
    detachedRoots: detachedRootsElsewhere ?? new Set<string>(),
    selectedId,
    viewedAgentTaskId,
    viewedRootId,
    selectAgent,
    handleSelectHistoryId,
    requestDeleteId: requestDelete,
    archiveAgentTask: isArchivedView ? unarchiveChain : archiveChain,
    archiveLabel: isArchivedView ? 'Unarchive' : 'Archive',
    detachAgentTask: detachAgentTaskById,
    cancelAgentTask,
    getAgentRootTaskId: (agentTaskId) => agentStore.getAgent(agentTaskId)?.rootTaskId,
    openContextMenuForId,
    preserveHistoryOrder: isSearchActive,
    pendingFollowUps,
  });

  const confirmDeleteScheduled = useCallback((scheduledAgentTaskId: string) => {
    setPendingDeleteId(null);
    api.deleteScheduledAgentTask(scheduledAgentTaskId)
      .then(() => loadScheduled())
      .catch((err) => console.error('[Sidebar] Failed to delete scheduled agent task', err));
  }, [loadScheduled]);

  const scheduledItems: AgentTaskRowProps[] = buildScheduledItems({
    scheduled,
    selectedScheduledAgentTaskId,
    onViewScheduledAgentTask,
    deleteScheduledAgentTask: requestDelete,
  });

  const unifiedItems: AgentTaskRowProps[] = viewMode !== 'scheduled'
    ? historyItems.map(item => ({
        ...item,
        isPendingDelete: item.id === pendingDeleteId,
        onConfirmDelete: confirmDelete,
        onCancelDeleteRequest: cancelDelete,
      }))
    : scheduledItems.map(item => ({
        ...item,
        isPendingDelete: item.id === pendingDeleteId,
        onConfirmDelete: confirmDeleteScheduled,
        onCancelDeleteRequest: cancelDelete,
      }));

  return (
    <div className={`sidebar ${isExpanded ? 'expanded' : 'collapsed'}`} data-expanded={isExpanded}>
      <div
        className="sidebar-content-layer sidebar-content-layer--collapsed"
        aria-hidden={isExpanded}
        inert={isExpanded ? '' : undefined}
      >
        <div style={{ padding: 'var(--padding-xs)' }}>
          <button className="sidebar-toggle-btn" onClick={onToggle} title="Show task history">
            <AgentTaskSidebarToggleIcon />
          </button>
        </div>
      </div>
      <div
        className="sidebar-content-layer sidebar-content-layer--expanded"
        aria-hidden={!isExpanded}
        inert={!isExpanded ? '' : undefined}
      >
      <div className="sidebar-header">
        <span className="sidebar-header-title">
          {viewMode === 'history' ? 'Tasks' : viewMode === 'scheduled' ? 'Scheduled' : 'Archived'}
        </span>
        <div style={{ display: 'flex', gap: 'var(--padding-xs)' }}>
          <button className="sidebar-toggle-btn" onClick={handleNewAgent} title="Start new agent">
            {viewMode !== 'scheduled' ? <PlusCircleIcon /> : <span style={{ fontSize: 14, lineHeight: 1 }}>+</span>}
          </button>
          <button
            className="sidebar-toggle-btn"
            onClick={() => switchViewMode(viewMode === 'scheduled' ? 'history' : 'scheduled')}
            title={viewMode === 'scheduled' ? 'View task history' : 'View scheduled tasks'}
            aria-pressed={viewMode === 'scheduled'}
          >
            <CalendarIcon />
          </button>
          <button
            className="sidebar-toggle-btn"
            onClick={() => switchViewMode(viewMode === 'archived' ? 'history' : 'archived')}
            title={viewMode === 'archived' ? 'Back to tasks' : 'Archived'}
            aria-label={viewMode === 'archived' ? 'Back to tasks' : 'Archived'}
            aria-pressed={viewMode === 'archived'}
          >
            <ArchiveBoxIcon />
          </button>
          <button className="sidebar-toggle-btn" onClick={onToggle} title="Hide task history">
            <AgentTaskSidebarToggleIcon />
          </button>
        </div>
      </div>

      <div className="sidebar-search">
        <input
          className="sidebar-search-input"
          type="text"
          placeholder={viewMode === 'history' ? 'Search tasks...' : viewMode === 'archived' ? 'Search archived...' : 'Search scheduled...'}
          value={searchQuery}
          onChange={e => {
            const value = e.target.value;
            setSearchQuery(value);
            if (viewMode !== 'scheduled') {
              handleSearch(value);
            } else {
              const lowered = value.toLowerCase();
              if (!lowered) {
                loadScheduled();
                return;
              }
              setScheduled(prev => prev.filter(s => s.title.toLowerCase().includes(lowered) || s.agent_task_text.toLowerCase().includes(lowered)));
            }
          }}
        />
      </div>

      <div className="sidebar-list" style={{ flex: 1 }}>
        {viewMode !== 'scheduled' && historyDeepSearching && !historyLoading && (
          <div style={{ padding: '6px 12px', fontSize: 11, color: 'var(--text-secondary)' }}>
            Searching full history...
          </div>
        )}
        {historyLoading && (
          <div className="empty-state">
            <div className="loading-spinner" />
            <span>{viewMode === 'scheduled' ? 'Loading scheduled jobs...' : viewMode === 'archived' ? 'Loading archived tasks...' : 'Loading tasks...'}</span>
          </div>
        )}
        {historyError && (
          <div className="empty-state">
            <WarningIcon size={16} />
            <span>{historyError}</span>
            <button className="action-btn" onClick={() => loadHistory()}>Retry</button>
          </div>
        )}
        {!historyLoading && !historyError && unifiedItems.length === 0 && (
          <div className="empty-state">
            <MicrophoneIcon size={24} />
            <span>{viewMode === 'scheduled' ? 'No scheduled tasks' : viewMode === 'archived' ? 'No archived tasks' : 'No tasks yet'}</span>
          </div>
        )}
        {unifiedItems.map(item => (
          <AgentTaskRow key={item.id} {...item} />
        ))}
      </div>

      {contextMenu && (
        <div
          className="context-menu"
          style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 100 }}
          onClick={e => e.stopPropagation()}
        >
          <button
            className="context-menu-item"
            onClick={() => {
              openDetachedAgentTask(contextMenu.rootTaskId ?? contextMenu.item.id);
              setContextMenu(null);
            }}
          >
            <OpenInSeparateWindowIcon size={10} />
            <span>Open in separate window</span>
          </button>
          {contextMenu.canArchive !== false && (
            <button
              className="context-menu-item"
              onClick={() => {
                const target = contextMenu.rootTaskId ?? contextMenu.item.id;
                void (isArchivedView ? unarchiveChain(target) : archiveChain(target));
              }}
            >
              <ArchiveBoxIcon size={10} />
              <span>{isArchivedView ? 'Unarchive' : 'Archive'}</span>
            </button>
          )}
          {contextMenu.canDelete !== false && (
            <button
              className="context-menu-item danger"
              onClick={() => requestDelete(contextMenu.item.id)}
            >
              <TrashIcon size={10} />
              <span>Delete</span>
            </button>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
