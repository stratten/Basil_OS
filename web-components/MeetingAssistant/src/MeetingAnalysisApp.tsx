import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { copyText, exportAnalysis, registerEventHandler, reportReady, toggleWindowCollapse, viewAnalysis } from './bridge/meetingBridge';
import { applyMeetingBridgeEvent, initialMeetingState } from './state/meetingReducer';
import AnalysisResults from './components/AnalysisResults';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';
import WindowChrome from './components/WindowChrome';
import { applyMeetingHostFonts, applyMeetingHostTheme } from './lib/hostAppearance';
import {
  analysisExportFilename,
  buildAnalysisExportText,
  completedAnalysisModes,
  formatSpeakerCount,
  type AnalysisModeId,
} from './lib/analysisModes';

const COPIED_CONFIRMATION_MS = 1500;

export default function MeetingAnalysisApp() {
  const [state, dispatch] = useReducer(applyMeetingBridgeEvent, initialMeetingState);
  const [tab, setTab] = useState<AnalysisModeId | null>(null);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);
  const [copied, setCopied] = useState(false);
  const copiedTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
  }, []);

  useEffect(() => {
    registerEventHandler((event) => dispatch(event));
    reportReady();
  }, []);

  useEffect(() => {
    applyMeetingHostTheme(state.theme);
    applyMeetingHostFonts(state.fonts);
  }, [state.theme, state.fonts]);

  const result = state.analysisResult;
  const analysisKey = result ? `${result.filename ?? ''}:${result.analyzedAt}` : '';
  const modes = useMemo(() => (result ? completedAnalysisModes(result) : []), [result]);
  const selectedTab = tab && modes.some((mode) => mode.id === tab) ? tab : (modes[0]?.id ?? null);
  const proposals = state.proposals.length > 0 ? state.proposals : (result?.suggestedActions ?? []);

  useEffect(() => {
    setTab(null);
  }, [analysisKey]);

  const exportText = result ? buildAnalysisExportText(result, proposals) : '';

  const copyAll = () => {
    copyText(exportText);
    setCopied(true);
    if (copiedTimerRef.current !== null) window.clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = window.setTimeout(() => {
      copiedTimerRef.current = null;
      setCopied(false);
    }, COPIED_CONFIRMATION_MS);
  };

  const handleToggleCollapse = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    toggleWindowCollapse(next);
  };

  useCollapseShortcut(handleToggleCollapse);

  return (
    <div className="basil-webkit-window-frame">
      <div className="basil-webkit-window-surface meeting-analysis-surface">
        <WindowChrome
          title="Meeting Analysis"
          subtitle={result?.meetingName && result.meetingName !== 'Meeting Analysis' ? result.meetingName : undefined}
          titleVariant="headline"
          isCollapsed={isCollapsed}
          isRecording={false}
          onToggleCollapse={handleToggleCollapse}
          trailing={result ? (
            <div className="meeting-window-chrome-trailing">
              <button
                type="button"
                className="meeting-window-chrome-action"
                title="Copy all results to clipboard"
                onClick={copyAll}
              >
                {copied ? <CopiedIcon /> : <CopyAllIcon />}
                {copied ? 'Copied' : 'Copy All'}
              </button>
              <button
                type="button"
                className="meeting-window-chrome-action"
                title="Export as Markdown"
                onClick={() => exportAnalysis(result.filename ?? 'meeting-analysis', 'markdown', exportText, analysisExportFilename(result))}
              >
                <ExportIcon />
                Export
              </button>
            </div>
          ) : null}
        />
        <div
          hidden={isContentCollapsed}
          aria-hidden={isContentCollapsed}
          inert={isContentCollapsed ? '' : undefined}
          style={isContentCollapsed ? undefined : { display: 'contents' }}
        >
        {state.ui?.isLoadingAnalysisResult ? (
          <div className="meeting-loading-state">Opening analysis…</div>
        ) : state.ui?.analysisResultLoadError ? (
          <div className="meeting-loading-state" role="alert">
            <span>{state.ui.analysisResultLoadError}</span>
            {state.ui.analysisResultRequestedFilename && <button type="button" onClick={() => viewAnalysis(state.ui!.analysisResultRequestedFilename!)}>Retry</button>}
          </div>
        ) : !result ? (
          <div className="meeting-loading-state">Loading analysis…</div>
        ) : (
          <>
            <div className="meeting-analysis-toolbar">
              <div className="meeting-analysis-metadata">
                <span>{result.formattedDuration}</span>
                <span>{formatSpeakerCount(result.speakerCount)}</span>
                <span>{result.modelUsed}</span>
                <span>Analyzed in {result.formattedProcessingTime}</span>
              </div>
              {modes.length > 1 && (
                <div className="meeting-analysis-tabs" role="tablist" aria-label="Analysis modes">
                  {modes.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      role="tab"
                      aria-selected={selectedTab === mode.id}
                      className={selectedTab === mode.id ? 'meeting-analysis-tab meeting-analysis-tab--active' : 'meeting-analysis-tab'}
                      onClick={() => setTab(mode.id)}
                    >
                      {mode.displayName}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <main className="meeting-analysis-content">
              {selectedTab ? (
                <AnalysisResults result={result} mode={selectedTab} proposals={proposals} />
              ) : (
                <p className="meeting-analysis-empty-state">No analysis results available</p>
              )}
            </main>
          </>
        )}
        </div>
      </div>
    </div>
  );
}

function CopyAllIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.2" />
      <path d="M10.5 5.5V3.8A1.3 1.3 0 0 0 9.2 2.5H3.8A1.3 1.3 0 0 0 2.5 3.8v5.4A1.3 1.3 0 0 0 3.8 10.5H5.5" />
    </svg>
  );
}

function CopiedIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="m3 8.2 3.1 3.1L13 4.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ExportIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M8 2.5v7.2" strokeLinecap="round" />
      <path d="M5.2 5.2 8 2.5l2.8 2.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 10.2V12a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 13 12v-1.8" strokeLinecap="round" />
    </svg>
  );
}
