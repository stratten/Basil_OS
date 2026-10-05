import { useCallback, useEffect, useRef, useState } from 'react';
import CrossfadeStack from '@shared/CrossfadeStack';
import PresenceRegion from '@shared/PresenceRegion';
import { closeWindow, minimizeWindow, onHistoryEvent, reportHistoryReady, toggleChromeCollapse } from '../bridge/historyBridge';
import { deleteHistoryEntry, fetchHistory, fetchHistoryDetail, type AssistantOutputHistoryDetail, type AssistantOutputHistoryEntry } from '../services/historyApi';
import { HistorySidebar, type HistoryModalityFilter } from '../components/history/HistorySidebar';
import { HistoryDetail } from '../components/history/HistoryDetail';
import { applyAssistantSessionTheme } from './themeCssVars';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import { BASIL_TEAM } from '@shared/teamIdentity';
import type { AssistantSessionThemePayload } from '../bridge/types';

export function AssistantOutputHistoryApp() {
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [theme, setTheme] = useState<AssistantSessionThemePayload | null>(null);
  const [entries, setEntries] = useState<AssistantOutputHistoryEntry[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AssistantOutputHistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const loadStateRef = useRef(loadState);
  loadStateRef.current = loadState;
  const [filter, setFilter] = useState<HistoryModalityFilter>('all');
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [chromeCollapsed, setChromeCollapsed] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AssistantOutputHistoryEntry | null>(null);
  const [nativeActionError, setNativeActionError] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const filterRef = useRef(filter);
  const debouncedQueryRef = useRef(debouncedQuery);
  const baseUrlRef = useRef(baseUrl);

  useEffect(() => {
    filterRef.current = filter;
    debouncedQueryRef.current = debouncedQuery;
    baseUrlRef.current = baseUrl;
  }, [filter, debouncedQuery, baseUrl]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const reload = useCallback((url: string, nextFilter: HistoryModalityFilter, nextQuery: string, options: { quiet?: boolean } = {}) => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setRefreshing(true);
    setLoadState((current) => (current === 'error' ? 'loading' : current));
    setErrorMessage(null);
    fetchHistory(url, {
      inputModality: nextFilter === 'all' ? null : nextFilter,
      query: nextQuery,
    })
      .then((fetched) => {
        if (requestGeneration.current !== generation) return;
        setEntries(fetched);
        setLoadState('ready');
        setRefreshing(false);
        setSelectedId((current) => (
          current != null && fetched.some((entry) => entry.id === current)
            ? current
            : fetched[0]?.id ?? null
        ));
      })
      .catch((error: unknown) => {
        if (requestGeneration.current !== generation) return;
        setRefreshing(false);
        if (options.quiet && loadStateRef.current === 'ready') return;
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load history');
        setLoadState('error');
      });
  }, []);

  useEffect(() => {
    const off = onHistoryEvent((event) => {
      if (event.type === 'init') {
        setBaseUrl(event.baseUrl);
        setTheme(event.theme);
      } else if (event.type === 'themeChanged') {
        const { type, ...rest } = event;
        void type;
        setTheme(rest);
      } else if (event.type === 'historyUpdated' && baseUrlRef.current) {
        reload(baseUrlRef.current, filterRef.current, debouncedQueryRef.current, { quiet: true });
      } else if (event.type === 'historyActionError') {
        setNativeActionError(event.message);
      }
    });
    reportHistoryReady();
    return off;
  }, [reload]);

  useEffect(() => {
    if (baseUrl) reload(baseUrl, filter, debouncedQuery);
  }, [baseUrl, filter, debouncedQuery, reload]);

  useEffect(() => {
    if (theme) applyAssistantSessionTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (!baseUrl || selectedId == null) {
      detailGeneration.current += 1;
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    const generation = detailGeneration.current + 1;
    detailGeneration.current = generation;
    setNativeActionError(null);
    setDetailLoading(true);
    fetchHistoryDetail(baseUrl, selectedId)
      .then((nextDetail) => {
        if (detailGeneration.current === generation) setDetail(nextDetail);
      })
      .catch(() => {
        if (detailGeneration.current === generation) setDetail(null);
      })
      .finally(() => {
        if (detailGeneration.current === generation) setDetailLoading(false);
      });
  }, [baseUrl, selectedId]);

  const removeEntry = async (id: number) => {
    if (!baseUrl) return;
    setActionError(null);
    try {
      await deleteHistoryEntry(baseUrl, id);
      setEntries((prev) => prev.filter((entry) => entry.id !== id));
      setSelectedId((current) => (current === id ? null : current));
      setPendingDelete(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to delete history entry');
      setPendingDelete(null);
    }
  };

  if (!theme) {
    return (
      <div className="basil-webkit-window-frame">
        <div className="assistant-output-history-shell assistant-output-history-shell--loading basil-webkit-window-surface">
          <span>Loading history…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="basil-webkit-window-frame">
      <div className="assistant-output-history-shell basil-webkit-window-surface">
        <div className="assistant-output-history-shell__titlebar">
          <div className="assistant-output-history-shell__titlebar-actions">
            <button type="button" onClick={closeWindow} aria-label="Close">
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="color-mix(in srgb, var(--secondary, #4c7bf0) 15%, transparent)" />
                <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary, #4c7bf0)" strokeWidth="1.6" strokeLinecap="round" />
                <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary, #4c7bf0)" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <button type="button" onClick={minimizeWindow} aria-label="Minimize">
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="color-mix(in srgb, var(--secondary, #4c7bf0) 15%, transparent)" />
                <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary, #4c7bf0)" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <button
              type="button"
              aria-label={chromeCollapsed ? 'Expand history' : 'Collapse history'}
              aria-pressed={chromeCollapsed}
              onClick={() => {
                const next = !chromeCollapsed;
                setChromeCollapsed(next);
                toggleChromeCollapse(next);
              }}
            >
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="color-mix(in srgb, var(--secondary, #4c7bf0) 15%, transparent)" />
                <path
                  d="M7 9l4 4 4-4"
                  fill="none"
                  stroke="var(--secondary, #4c7bf0)"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    transformBox: 'fill-box',
                    transformOrigin: 'center',
                    transition: 'transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1)',
                    transform: chromeCollapsed ? 'rotate(-90deg)' : undefined,
                  }}
                />
              </svg>
            </button>
          </div>
          <img
            className="assistant-output-history-shell__dill"
            src={new URL('../../../shared/assets/native-symbols/dill-icon.png', import.meta.url).href}
            alt=""
          />
          <span>{BASIL_TEAM.assistantSession.pairedName} History</span>
        </div>
        {!chromeCollapsed && (
          <div className="assistant-output-history-shell__body">
            <HistorySidebar
              entries={entries}
              selectedId={selectedId}
              onSelect={setSelectedId}
              collapsed={sidebarCollapsed}
              onToggleCollapsed={() => setSidebarCollapsed((prev) => !prev)}
              filter={filter}
              onFilterChange={setFilter}
              query={query}
              onQueryChange={setQuery}
              onDelete={setPendingDelete}
              loadState={loadState}
              errorMessage={errorMessage}
              onRetry={() => baseUrl && reload(baseUrl, filter, debouncedQuery)}
              refreshing={refreshing}
              actionError={actionError}
              onDismissActionError={() => setActionError(null)}
            />
            {baseUrl && (
              <CrossfadeStack
                contentKey={detail ? `detail-${detail.id}` : detailLoading ? 'loading' : 'empty'}
                className="assistant-output-history-detail-stack basil-crossfade"
                layerClassName="basil-crossfade-layer"
                settleWithoutTransition
              >
                <HistoryDetail
                  entry={detail}
                  baseUrl={baseUrl}
                  loading={detailLoading && detail === null}
                  nativeActionError={nativeActionError}
                  onClearNativeActionError={() => setNativeActionError(null)}
                />
              </CrossfadeStack>
            )}
          </div>
        )}
        <PresenceRegion visible={pendingDelete !== null} className="assistant-output-history-shell__confirm basil-presence--modal" settleWithoutTransition>
          {pendingDelete && (
            <>
              <p>Are you sure you want to delete &quot;{plainMarkdownText(pendingDelete.title) || 'Untitled output'}&quot;?</p>
              <button type="button" onClick={() => setPendingDelete(null)}>Cancel</button>
              <button type="button" onClick={() => { void removeEntry(pendingDelete.id); }}>Delete</button>
            </>
          )}
        </PresenceRegion>
      </div>
        </div>
  );
}
