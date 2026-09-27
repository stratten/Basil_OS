import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { HistorySidebarHeader } from '../../../shared/HistorySidebarControls';
import TokenizedSelect from '@shared/TokenizedSelect';
import { useHistoryRowRevealDelete } from '@shared/useHistoryRowRevealDelete';
import type { MeetingHistorySearchFiltersDTO, MeetingListItemDTO, MeetingSearchTermModeDTO } from '../bridge/types';
import { deleteMeeting, loadMoreMeetings, selectMeeting, setMeetingSearch, setMeetingSearchFilters, setSidebarCollapsed, startNewMeeting, viewAnalysis } from '../bridge/meetingBridge';

interface MeetingHistorySidebarProps {
  history: MeetingListItemDTO[];
  selectedMeetingId: string | null;
  searchText: string;
  searchFilters: MeetingHistorySearchFiltersDTO;
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  loadMoreError: string | null;
  activeAnalysisMeetingId: string | null;
}

function MeetingHistorySidebar({ history, selectedMeetingId, searchText, searchFilters, isLoading, isLoadingMore, hasMore, loadMoreError, activeAnalysisMeetingId }: MeetingHistorySidebarProps) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [draftFilters, setDraftFilters] = useState(searchFilters);
  const draftFiltersRef = useRef(searchFilters);
  const pendingFiltersRef = useRef<MeetingHistorySearchFiltersDTO | null>(null);
  useEffect(() => {
    // A selection can cause an unrelated UI snapshot before the asynchronous
    // filter intent has been processed. Do not let that stale snapshot erase
    // values the user has just entered; synchronize only once Swift echoes
    // the dispatched filter state.
    if (pendingFiltersRef.current && !filterStatesMatch(searchFilters, pendingFiltersRef.current)) return;
    pendingFiltersRef.current = null;
    draftFiltersRef.current = searchFilters;
    setDraftFilters(searchFilters);
  }, [searchFilters]);
  const updateFilters = useCallback((change: Partial<MeetingHistorySearchFiltersDTO>) => {
    const nextFilters = { ...draftFiltersRef.current, ...change };
    draftFiltersRef.current = nextFilters;
    pendingFiltersRef.current = nextFilters;
    setDraftFilters(nextFilters);
    setMeetingSearchFilters(nextFilters);
  }, []);
  const activeFilterCount = countActiveFilters(draftFilters);
  const isSearching = Boolean(searchText.trim()) || activeFilterCount > 0;

  return (
    <aside className="meeting-history-sidebar" aria-label="Meeting history">
      <HistorySidebarHeader title="History" onStartNew={startNewMeeting} onCollapse={() => setSidebarCollapsed(true)} startLabel="Start new meeting" collapseLabel="Hide meeting history" />
      <div className="meeting-history-search-shell">
        <SearchIcon />
        <input className="meeting-history-search" type="search" value={searchText} onChange={(event) => setMeetingSearch(event.target.value)} placeholder="Search meetings..." aria-label="Search meetings" />
        <TermModeToggle mode={draftFilters.queryMode} onToggle={() => updateFilters({ queryMode: toggleMode(draftFilters.queryMode) })} label="Search meetings" />
        <button type="button" className={activeFilterCount ? "meeting-history-filter-button meeting-history-filter-button--active" : "meeting-history-filter-button"} aria-label="Show advanced filters" aria-controls="meeting-advanced-filters" aria-expanded={filtersExpanded} onClick={() => setFiltersExpanded((expanded) => !expanded)}>
          <FilterIcon />
          {activeFilterCount > 0 && <span>{activeFilterCount}</span>}
        </button>
        {searchText && <button type="button" className="meeting-history-search-clear" onClick={() => setMeetingSearch('')} aria-label="Clear search">×</button>}
      </div>
      {filtersExpanded && <AdvancedFilters filters={draftFilters} onChange={updateFilters} />}
      {isLoading && <div className="meeting-history-empty-state">Loading meetings…</div>}
      {!isLoading && history.length === 0 && (
        <div className="meeting-history-empty-state">
          <EmptyHistoryIcon isSearching={isSearching} />
          <span>{isSearching ? 'No matching meetings' : 'No past meetings'}</span>
        </div>
      )}
      <ul className="meeting-history-list">
        {history.map((meeting) => <MeetingHistoryRow
          key={meeting.id}
          meeting={meeting}
          isSelected={meeting.id === selectedMeetingId}
          isAnalyzing={meeting.id === activeAnalysisMeetingId}
          pendingDelete={pendingDeleteId === meeting.id}
          onDeleteRequest={() => setPendingDeleteId(meeting.id)}
          onDeleteCancel={() => setPendingDeleteId(null)}
          onDeleteConfirm={() => { deleteMeeting(meeting.id); setPendingDeleteId(null); }}
        />)}
      </ul>
      {loadMoreError && (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{loadMoreError}</span>
          <button type="button" onClick={loadMoreMeetings}>Retry</button>
        </div>
      )}
      {!loadMoreError && hasMore && (
        <button
          type="button"
          className="meeting-history-load-more-button"
          onClick={loadMoreMeetings}
          disabled={isLoadingMore}
          aria-busy={isLoadingMore}
        >
          {isLoadingMore ? 'Loading more meetings…' : 'Load more meetings'}
        </button>
      )}
    </aside>
  );
}

export default memo(MeetingHistorySidebar);

function AdvancedFilters({ filters, onChange }: { filters: MeetingHistorySearchFiltersDTO; onChange: (change: Partial<MeetingHistorySearchFiltersDTO>) => void }) {
  return <section id="meeting-advanced-filters" className="meeting-advanced-filters" aria-label="Advanced meeting filters">
    <TextFilterRow label="Meeting name" value={filters.name} mode={filters.nameMode} placeholder="Name contains..." onValueChange={(name) => onChange({ name })} onModeToggle={() => onChange({ nameMode: toggleMode(filters.nameMode) })} />
    <TextFilterRow label="Purpose" value={filters.purpose} mode={filters.purposeMode} placeholder="Purpose contains..." onValueChange={(purpose) => onChange({ purpose })} onModeToggle={() => onChange({ purposeMode: toggleMode(filters.purposeMode) })} />
    <TextFilterRow label="Participants" value={filters.participants} mode={filters.participantsMode} placeholder="Names or emails..." onValueChange={(participants) => onChange({ participants })} onModeToggle={() => onChange({ participantsMode: toggleMode(filters.participantsMode) })} />
    <TextFilterRow label="Transcript" value={filters.transcript} mode={filters.transcriptMode} placeholder="Spoken text contains..." onValueChange={(transcript) => onChange({ transcript })} onModeToggle={() => onChange({ transcriptMode: toggleMode(filters.transcriptMode) })} />
    <TextFilterRow label="Audio source" value={filters.source} mode={filters.sourceMode} placeholder="Microphone, Zoom..." onValueChange={(source) => onChange({ source })} onModeToggle={() => onChange({ sourceMode: toggleMode(filters.sourceMode) })} />
    <div className="meeting-advanced-filter-grid">
      <label>From<input type="date" value={filters.startDate ?? ''} max={filters.endDate ?? undefined} onChange={(event) => onChange({ startDate: event.target.value || null })} /></label>
      <label>To<input type="date" value={filters.endDate ?? ''} min={filters.startDate ?? undefined} onChange={(event) => onChange({ endDate: event.target.value || null })} /></label>
      <label>Processing<TokenizedSelect value={filters.processing} ariaLabel="Processing" onValueChange={(value) => onChange({ processing: value as MeetingHistorySearchFiltersDTO['processing'] })} options={[{ value: 'any', label: 'Any' }, { value: 'complete', label: 'Complete' }, { value: 'incomplete', label: 'Needs processing' }]} /></label>
      <label>Analysis<TokenizedSelect value={filters.analysis} ariaLabel="Analysis" onValueChange={(value) => onChange({ analysis: value as MeetingHistorySearchFiltersDTO['analysis'] })} options={[{ value: 'any', label: 'Any' }, { value: 'has_analysis', label: 'Has analysis' }, { value: 'no_analysis', label: 'No analysis' }]} /></label>
    </div>
    <button type="button" className="meeting-advanced-filters-clear" onClick={() => onChange({ ...clearedFilters, queryMode: filters.queryMode })}>Clear filters</button>
  </section>;
}

const clearedFilters: Omit<MeetingHistorySearchFiltersDTO, 'queryMode'> = {
  name: '', nameMode: 'and', purpose: '', purposeMode: 'and', participants: '', participantsMode: 'and', transcript: '', transcriptMode: 'and', source: '', sourceMode: 'and', startDate: null, endDate: null, processing: 'any', analysis: 'any',
};

function TextFilterRow({ label, value, mode, placeholder, onValueChange, onModeToggle }: { label: string; value: string; mode: MeetingSearchTermModeDTO; placeholder: string; onValueChange: (value: string) => void; onModeToggle: () => void }) {
  return <label className="meeting-advanced-filter-text-row"><span>{label}</span><span className="meeting-advanced-filter-input"><input type="search" value={value} placeholder={placeholder} aria-label={label} onChange={(event) => onValueChange(event.target.value)} /><TermModeToggle mode={mode} onToggle={onModeToggle} label={label} /></span></label>;
}

function TermModeToggle({ mode, onToggle, label }: { mode: MeetingSearchTermModeDTO; onToggle: () => void; label: string }) {
  const alternate = mode === 'and' ? 'or' : 'and';
  return <button type="button" className="meeting-search-term-mode" aria-label={`${label}: match ${mode === 'and' ? 'all' : 'any'} comma-separated values`} aria-pressed={mode === 'or'} title={`Match ${mode === 'and' ? 'all' : 'any'} comma-separated values`} onClick={onToggle}><span className={mode === 'and' ? 'is-selected' : ''}>AND</span><span className={alternate === 'and' ? 'is-selected' : ''}>OR</span></button>;
}

function toggleMode(mode: MeetingSearchTermModeDTO): MeetingSearchTermModeDTO {
  return mode === 'and' ? 'or' : 'and';
}

function countActiveFilters(filters: MeetingHistorySearchFiltersDTO): number {
  return [filters.name, filters.purpose, filters.participants, filters.transcript, filters.source, filters.startDate, filters.endDate].filter(Boolean).length + Number(filters.processing !== 'any') + Number(filters.analysis !== 'any');
}

function filterStatesMatch(left: MeetingHistorySearchFiltersDTO, right: MeetingHistorySearchFiltersDTO): boolean {
  return left.queryMode === right.queryMode
    && left.name === right.name && left.nameMode === right.nameMode
    && left.purpose === right.purpose && left.purposeMode === right.purposeMode
    && left.participants === right.participants && left.participantsMode === right.participantsMode
    && left.transcript === right.transcript && left.transcriptMode === right.transcriptMode
    && left.source === right.source && left.sourceMode === right.sourceMode
    && left.startDate === right.startDate && left.endDate === right.endDate
    && left.processing === right.processing && left.analysis === right.analysis;
}

interface MeetingHistoryRowProps {
  meeting: MeetingListItemDTO;
  isSelected: boolean;
  isAnalyzing: boolean;
  pendingDelete: boolean;
  onDeleteRequest: () => void;
  onDeleteCancel: () => void;
  onDeleteConfirm: () => void;
}

function MeetingHistoryRow({
  meeting,
  isSelected,
  isAnalyzing,
  pendingDelete,
  onDeleteRequest,
  onDeleteCancel,
  onDeleteConfirm,
}: MeetingHistoryRowProps) {
  const revealDelete = useHistoryRowRevealDelete({ enabled: !isAnalyzing && !pendingDelete });
  const requestDelete = () => {
    if (isAnalyzing) return;
    revealDelete.close();
    onDeleteRequest();
  };
  const handleSelectMeeting = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    selectMeeting(meeting.id);
  };

  return (
    <li className={isSelected ? 'meeting-history-item meeting-history-item--selected' : 'meeting-history-item'} onWheel={revealDelete.handleWheel}>
      {revealDelete.isOpen && (
        <button type="button" className="meeting-history-swipe-delete-button" onClick={requestDelete}>Delete</button>
      )}
      <div
        className="meeting-history-row-content"
        style={{ transform: revealDelete.offset > 0 ? `translateX(-${revealDelete.offset}px)` : undefined }}
      >
        <button type="button" className="meeting-history-item-button" onClick={handleSelectMeeting}>
          <span className="meeting-history-item-name">{meeting.name}</span>
          <span className="meeting-history-item-date-row">
            <span className="meeting-history-item-date">{meeting.formattedDate}</span>
            {meeting.durationSeconds !== null && (
              <span className="meeting-history-item-duration"><ClockIcon />{meeting.shortFormattedDuration}</span>
            )}
          </span>
          {(isAnalyzing || meeting.isPostProcessed || meeting.analysisSummary) && (
            <span className="meeting-history-item-status-row">
              {isAnalyzing ? (
                <span className="meeting-history-analysis-running"><AnalysisProgressIcon />Analyzing…</span>
              ) : (
                <>
                  {meeting.isPostProcessed && <span><ProcessedIcon />Processed</span>}
                  {meeting.analysisSummary && (
                    <span>
                      <SparklesIcon />
                      {meeting.analysisSummary.pendingActionCount && meeting.analysisSummary.pendingActionCount > 0
                        ? `${meeting.analysisSummary.pendingActionCount} pending`
                        : 'Analyzed'}
                    </span>
                  )}
                </>
              )}
            </span>
          )}
        </button>
        {meeting.analysisSummary && (
          <button
            type="button"
            className="meeting-history-analysis-quick-action"
            aria-label={`Open latest analysis for ${meeting.name}`}
            title="Open latest analysis"
            onClick={() => viewAnalysis(meeting.analysisSummary!.latestFilename)}
          >
            <OpenAnalysisIcon />
          </button>
        )}
        {pendingDelete ? (
          <span className="meeting-history-delete-confirm">
            <span>Delete?</span>
            <button type="button" onClick={onDeleteConfirm}>Delete</button>
            <button type="button" onClick={onDeleteCancel}>Cancel</button>
          </span>
        ) : (
          <button
            type="button"
            className="meeting-history-item-delete"
            onClick={requestDelete}
            disabled={isAnalyzing}
            aria-label={`Delete ${meeting.name}`}
            title={isAnalyzing ? 'Cannot delete while analysis is in progress' : `Delete ${meeting.name}`}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M3.25 4.25h7.5M5.25 4.25V2.75h3.5v1.5M4.25 4.25l.5 7h4.5l.5-7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>
    </li>
  );
}

function SearchIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.2" /><path d="m10 10 3.2 3.2" strokeLinecap="round" /></svg>;
}

function FilterIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d="M2 3h12L9.4 8.2v4.1l-2.8.9V8.2L2 3Z" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function ClockIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="M8 4.7v3.6l2.4 1.4" strokeLinecap="round" /></svg>;
}

function ProcessedIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><path d="M2 8h2l1-3 2 6 2-6 1 3h2" /><path d="m11.3 11.6 1.1 1.1 2-2.3" /></svg>;
}

function SparklesIcon() {
  return <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M6.3 1.5c.4 2.5 1.7 3.8 4.2 4.2-2.5.4-3.8 1.7-4.2 4.2-.4-2.5-1.7-3.8-4.2-4.2 2.5-.4 3.8-1.7 4.2-4.2Zm5.1 7.3c.2 1.5 1 2.3 2.5 2.5-1.5.2-2.3 1-2.5 2.5-.2-1.5-1-2.3-2.5-2.5 1.5-.2 2.3-1 2.5-2.5Z" /></svg>;
}

function AnalysisProgressIcon() {
  return <svg className="meeting-history-analysis-progress-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M13.2 8A5.2 5.2 0 1 1 8 2.8" strokeLinecap="round" /></svg>;
}

function OpenAnalysisIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><rect x="2.2" y="4.5" width="9.3" height="9.3" rx="1.2" /><path d="M7.5 2.2h6.3v6.3M13.5 2.5 7.2 8.8" /></svg>;
}

function EmptyHistoryIcon({ isSearching }: { isSearching: boolean }) {
  return isSearching ? <SearchIcon /> : <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="5" y="7" width="22" height="20" rx="3" /><path d="M10 4v6M22 4v6M5 13h22" /><circle cx="21" cy="21" r="4" /><path d="M21 18.8v2.5l1.7 1" /></svg>;
}
