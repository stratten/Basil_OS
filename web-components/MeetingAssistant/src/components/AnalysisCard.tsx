import { useState } from 'react';
import PresenceRegion from '@shared/PresenceRegion';
import NativeSymbolIcon, { type NativeSymbolName } from '../../../shared/NativeSymbolIcon';
import ReasoningModelPicker, { type SharedReasoningModel } from '../../../shared/ReasoningModelPicker';
import type { AnalysisMetadataEntryDTO, MeetingUIStateDTO } from '../bridge/types';
import { deleteAnalysis, setAnalysisConfiguration, startAnalysis, viewAnalysis } from '../bridge/meetingBridge';

const ANALYSIS_MODES: Array<{ id: string; label: string; description: string; icon: NativeSymbolName }> = [
  { id: 'action_items', label: 'Action Items', description: 'Extract tasks and action items', icon: 'analysisActionItems' },
  { id: 'suggested_actions', label: 'To-Do Candidates', description: 'Review durable follow-ups Basil identified', icon: 'analysisSuggestedActions' },
  { id: 'summary', label: 'Summary', description: 'Generate meeting summary', icon: 'analysisSummary' },
  { id: 'decisions', label: 'Key Decisions', description: 'Identify key decisions', icon: 'analysisDecisions' },
  { id: 'questions', label: 'Questions & Answers', description: 'Extract Q&A pairs', icon: 'analysisQuestions' },
  { id: 'sentiment', label: 'Sentiment Analysis', description: 'Analyze tone and engagement', icon: 'analysisSentiment' },
  { id: 'custom', label: 'Custom Analysis', description: 'Custom analysis', icon: 'analysisCustom' },
];

export default function AnalysisCard({ ui, analysisHistory }: { ui: MeetingUIStateDTO; analysisHistory: AnalysisMetadataEntryDTO[] }) {
  const [pendingDeleteFilename, setPendingDeleteFilename] = useState<string | null>(null);
  const isViewingActiveAnalysis = ui.isAnalyzing
    && ui.activeAnalysisMeetingId !== null
    && ui.activeAnalysisMeetingId === ui.displayedMeetingWorkOwnerId;
  const justCompletedForDisplayedMeeting = ui.analysisJustCompleted
    && ui.activeAnalysisMeetingId !== null
    && ui.activeAnalysisMeetingId === ui.displayedMeetingWorkOwnerId;
  const analysisModels = [
    ...ui.localAnalysisModels,
    ...(ui.useApiModelsForAnalysis ? ui.apiAnalysisModels : []),
  ];
  const groupedAnalysisModels: SharedReasoningModel[] = analysisModels.map((model) => ({
    id: model.id,
    name: model.name,
    display_name: model.displayName,
    category: model.category,
  }));
  const toggleMode = (modeId: string) => {
    const next = ui.selectedAnalysisModes.includes(modeId)
      ? ui.selectedAnalysisModes.filter((mode) => mode !== modeId)
      : [...ui.selectedAnalysisModes, modeId];
    setAnalysisConfiguration({ modes: next });
  };
  const analysisProgressMessage = ui.analysisMessage
    || (ui.currentAnalysisMode ? `Analyzing: ${ui.currentAnalysisMode}` : 'Analyzing…');

  return (
    <section className="meeting-analysis-card">
      <button type="button" className="meeting-analysis-disclosure" onClick={() => setAnalysisConfiguration({ isExpanded: !ui.isAnalysisSectionExpanded })} aria-expanded={ui.isAnalysisSectionExpanded}>
        <ChevronIcon expanded={ui.isAnalysisSectionExpanded} />
        Analysis
        {!ui.isAnalysisSectionExpanded && analysisHistory.length > 0 && <span className="meeting-analysis-count">{analysisHistory.length}</span>}
        {!ui.isAnalysisSectionExpanded && isViewingActiveAnalysis && ui.analysisStartedAutomatically && <span className="meeting-analysis-running">Automatic analysis running</span>}
      </button>
      <PresenceRegion visible={ui.isAnalysisSectionExpanded} className="basil-presence" settleWithoutTransition>
        <>
      <div className="meeting-analysis-configuration">
      <div className="meeting-analysis-intro">
        <p>Analyze transcript to extract insights</p>
        <label className="meeting-analysis-model-row">
          <span>Reasoning Model:</span>
          <ReasoningModelPicker
            models={groupedAnalysisModels}
            selectedModelId={ui.selectedAnalysisModelId ?? undefined}
            disabled={ui.isAnalyzing || ui.isLoadingAnalysisModels}
            ariaLabel="Reasoning model"
            placeholder={ui.isLoadingAnalysisModels ? 'Loading models…' : 'Choose a model'}
            onModelChange={(modelId) => setAnalysisConfiguration({ modelId })}
          />
        </label>
      </div>
      <div className="meeting-analysis-config-body">
      <div className="meeting-analysis-mode-list">
        <span className="meeting-analysis-field-label">Analysis Types:</span>
        {ANALYSIS_MODES.map((mode) => (
          <label key={mode.id} className="meeting-analysis-mode-checkbox">
            <input
              type="checkbox"
              checked={ui.selectedAnalysisModes.includes(mode.id)}
              disabled={ui.isAnalyzing}
              onChange={() => toggleMode(mode.id)}
            />
            <span className="meeting-switch-track" aria-hidden="true" />
            <NativeSymbolIcon name={mode.icon} className="meeting-analysis-mode-icon" />
            <span className="meeting-analysis-mode-copy"><strong>{mode.label}</strong><small>{mode.description}</small></span>
          </label>
        ))}
      </div>
      <div className="meeting-analysis-instructions-column">
      <label className="meeting-analysis-field-label" htmlFor="meeting-analysis-instructions">Custom Instructions (optional):</label>
      <textarea
        id="meeting-analysis-instructions"
        className="meeting-analysis-custom-instructions"
        placeholder="Add custom instructions to augment selected modes"
        value={ui.analysisCustomInstructions}
        disabled={ui.isAnalyzing}
        onChange={(event) => setAnalysisConfiguration({ customInstructions: event.target.value })}
      />
      {isViewingActiveAnalysis ? (
        <div className="meeting-analysis-progress">
          <div className="meeting-progress-bar"><div className="meeting-progress-bar-fill" style={{ width: `${Math.round(ui.analysisProgress * 100)}%` }} /></div>
          <span>{analysisProgressMessage}<span className="meeting-analysis-progress-percent">{Math.round(ui.analysisProgress * 100)}%</span></span>
        </div>
      ) : (
      <button
        type="button"
        className="meeting-start-analysis-button"
        onClick={startAnalysis}
        disabled={ui.isAnalyzing || ui.selectedAnalysisModes.length === 0 || !ui.hasTranscription || !ui.selectedAnalysisModelId}
      >
        <SparklesIcon />
        Analyze
      </button>
      )}
      {justCompletedForDisplayedMeeting && <p className="meeting-analysis-complete-notice">Analysis complete</p>}
      </div>
      </div>
      </div>
      <h4 className="meeting-analysis-history-heading">Previous Analyses</h4>
      {ui.isLoadingAnalysisHistory && analysisHistory.length === 0 && <p className="meeting-analysis-history-loading">Loading…</p>}
      {!ui.isLoadingAnalysisHistory && analysisHistory.length === 0 && (
        <p className="meeting-analysis-history-empty">No analyses yet for this meeting.</p>
      )}
      {analysisHistory.length > 0 && <div className="meeting-analysis-history-table">
        <div className="meeting-analysis-history-header"><span>Date &amp; Time</span><span>Analysis Types</span><span>Model</span><span>Actions</span></div>
      <ul className="meeting-analysis-history-list">
        {analysisHistory.map((entry) => (
          <li key={entry.id} className="meeting-analysis-history-item">
            <span>{entry.formattedDate}</span>
            <span>{entry.modesDisplay}</span>
            <span title={entry.modelUsed}>{entry.shortModelName || entry.modelUsed}</span>
            {pendingDeleteFilename === entry.filename ? (
              <span className="meeting-analysis-delete-confirm">
                <span className="meeting-analysis-delete-confirm__label">Delete?</span>
                <span className="meeting-analysis-delete-confirm__actions">
                  <button type="button" onClick={() => { deleteAnalysis(entry.filename); setPendingDeleteFilename(null); }}>Delete</button>
                  <button type="button" onClick={() => setPendingDeleteFilename(null)}>Cancel</button>
                </span>
              </span>
            ) : (
              <span className="meeting-analysis-history-actions"><button type="button" onClick={() => viewAnalysis(entry.filename)} disabled={ui.isLoadingAnalysisResult}>{ui.isLoadingAnalysisResult ? 'Opening…' : 'View'}</button><button type="button" className="meeting-analysis-history-delete" onClick={() => setPendingDeleteFilename(entry.filename)} aria-label={`Delete analysis from ${entry.formattedDate}`}>Delete</button></span>
            )}
          </li>
        ))}
      </ul>
      </div>}
      {ui.analysisResultLoadError && <p className="meeting-analysis-history-error" role="alert">{ui.analysisResultLoadError}</p>}
        </>
      </PresenceRegion>
    </section>
  );
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return <svg className={`meeting-analysis-chevron${expanded ? ' is-expanded' : ''}`} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function SparklesIcon() {
  return <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M6.3 1.5c.4 2.5 1.7 3.8 4.2 4.2-2.5.4-3.8 1.7-4.2 4.2-.4-2.5-1.7-3.8-4.2-4.2 2.5-.4 3.8-1.7 4.2-4.2Zm5.1 7.3c.2 1.5 1 2.3 2.5 2.5-1.5.2-2.3 1-2.5 2.5-.2-1.5-1-2.3-2.5-2.5 1.5-.2 2.3-1 2.5-2.5Z" /></svg>;
}
