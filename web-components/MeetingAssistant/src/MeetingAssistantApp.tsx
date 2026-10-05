import { cloneElement, useEffect, useMemo, useReducer, useState, type HTMLAttributes, type ReactElement } from 'react';
import { registerEventHandler, reportReady, setSidebarCollapsed, toggleWindowCollapse } from './bridge/meetingBridge';
import { applyMeetingBridgeEvent, initialMeetingState } from './state/meetingReducer';
import WindowChrome from './components/WindowChrome';
import MeetingHistorySidebar from './components/MeetingHistorySidebar';
import MeetingMetadataForm from './components/MeetingMetadataForm';
import AudioSourceControls from './components/AudioSourceControls';
import RecordingControls from './components/RecordingControls';
import TranscriptPanel from './components/TranscriptPanel';
import TranscriptToolsCard from './components/TranscriptToolsCard';
import AnalysisCard from './components/AnalysisCard';
import { applyMeetingHostFonts, applyMeetingHostTheme } from './lib/hostAppearance';
import { CollapsedHistoryRail } from '../../shared/HistorySidebarControls';
import CollapsibleSidebar from '@shared/CollapsibleSidebar';
import AnimatedBubble from '../../shared/bubble/AnimatedBubble';
import { useMeetingMeter } from './bridge/meetingMeterStore';

export default function MeetingAssistantApp() {
  const [state, dispatch] = useReducer(applyMeetingBridgeEvent, initialMeetingState);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [embedded] = useState(
    () => document.documentElement.dataset.meetingAssistantEmbedded === 'true',
  );

  useEffect(() => {
    registerEventHandler((event) => dispatch(event));
    reportReady();
  }, []);

  useEffect(() => {
    applyMeetingHostTheme(state.theme);
    applyMeetingHostFonts(state.fonts);
  }, [state.theme, state.fonts]);

  const ui = state.ui;

  const handleToggleCollapse = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    toggleWindowCollapse(next);
  };

  const content = useMemo<ReactElement<HTMLAttributes<HTMLDivElement>>>(() => {
    if (!state.connected || !ui) {
      return <div className="meeting-loading-state">Connecting to Notetaker…</div>;
    }
    return (
      <div className="meeting-body">
        <CollapsibleSidebar
          element="div"
          expanded={!ui.isSidebarCollapsed}
          className="meeting-history-collapsible"
          collapsedContent={(
            <aside className="meeting-history-sidebar meeting-history-sidebar--collapsed" aria-label="Meeting history">
              <CollapsedHistoryRail ariaLabel="Show meeting history" title="Show meeting history" onExpand={() => setSidebarCollapsed(false)} />
            </aside>
          )}
        >
          <MeetingHistorySidebar
            history={state.history}
            selectedMeetingId={ui.selectedMeetingId}
            searchText={ui.meetingSearchText}
            searchFilters={ui.meetingSearchFilters}
            isLoading={ui.isLoadingMeetings}
            isLoadingMore={ui.isLoadingMoreMeetings}
            hasMore={ui.hasMoreMeetings}
            loadMoreError={ui.meetingHistoryLoadMoreError}
            activeAnalysisMeetingId={ui.isAnalyzing ? ui.activeAnalysisMeetingId : null}
          />
        </CollapsibleSidebar>
        <div className="meeting-main-column">
          {state.lastValidationError && (
            <p className="meeting-audio-recovery-notice" role="alert">
              {state.lastValidationError.message}
            </p>
          )}
          <MeetingMetadataForm
            name={ui.meetingName}
            purpose={ui.meetingPurpose}
            participants={ui.meetingParticipants}
            isViewingPastMeeting={ui.isViewingPastMeeting}
          />
          <AudioSourceControls ui={ui} />
          <TranscriptPanel transcript={state.transcript} ui={ui} />
          <RecordingControls ui={ui} />
          {!ui.isRecording && (ui.hasRecordedAudio || ui.hasTranscription) && (
            <div className="meeting-lower-tools">
              {ui.hasRecordedAudio && <TranscriptToolsCard ui={ui} />}
              {ui.hasTranscription && (
                <div className="meeting-analysis-scroll-region">
                  <AnalysisCard ui={ui} analysisHistory={state.analysisHistory} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }, [state, ui]);

  return (
    <div className={`basil-webkit-window-frame${embedded ? ' basil-webkit-window-frame--embedded' : ''}`}>
      <div className={`basil-webkit-window-surface meeting-assistant-surface${embedded ? ' meeting-assistant-surface--embedded' : ''}`}>
        {!embedded && (
          <WindowChrome
            title="Notetaker"
            subtitle={ui?.isRecording ? `${ui.isCapturePaused ? 'Paused' : 'Recording'} · ${ui.recordingTimeString}` : undefined}
            titleVariant="callout"
            featureIcon="microphone"
            isCollapsed={isCollapsed}
            onToggleCollapse={handleToggleCollapse}
            isRecording={Boolean(ui?.isRecording && !ui.isCapturePaused)}
            bubble={<MeetingAudioBubble ui={ui} />}
            canCollapse
          />
        )}
        {cloneElement(content, {
          hidden: isCollapsed,
          'aria-hidden': isCollapsed,
          inert: isCollapsed ? '' : undefined,
        })}
      </div>
    </div>
  );
}

function MeetingAudioBubble({ ui }: { ui: typeof initialMeetingState.ui }) {
  const meter = useMeetingMeter();
  const bubble = meetingBubblePresentation(ui, meter.microphoneAudioLevel);
  return <AnimatedBubble size={44} mode={bubble.mode} baseColor={bubble.baseColor} accentColor={bubble.accentColor} audioLevel={bubble.audioLevel} />;
}

function meetingBubblePresentation(ui: typeof initialMeetingState.ui, audioLevel: number) {
  const isViewingActivePostProcessingMeeting = ui?.isPostProcessing
    && ui.activePostProcessingMeetingId === ui.displayedMeetingWorkOwnerId;
  const isViewingActiveAnalysisMeeting = ui?.isAnalyzing
    && ui.activeAnalysisMeetingId === ui.displayedMeetingWorkOwnerId;
  // Recording red is reserved for a hot microphone; a paused capture is not listening.
  if (ui?.isRecording && ui.isCapturePaused) {
    return {
      mode: 'ambient' as const,
      baseColor: 'var(--warning-base)',
      accentColor: 'color-mix(in srgb, var(--warning-base) 45%, var(--background-primary))',
      audioLevel: 0,
    };
  }
  if (ui?.isRecording) {
    return {
      mode: 'audioResponsive' as const,
      baseColor: 'var(--recording-base)',
      accentColor: 'var(--recording-accent)',
      audioLevel,
    };
  }
  if (ui?.connectionState === 'connecting' || ui?.transcriptionState === 'loadingModels' || isViewingActivePostProcessingMeeting || isViewingActiveAnalysisMeeting) {
    return {
      mode: 'processing' as const,
      baseColor: 'var(--processing-base)',
      accentColor: 'var(--processing-accent)',
      audioLevel: 0,
    };
  }
  return {
    mode: 'ambient' as const,
    baseColor: 'var(--ready-base)',
    accentColor: 'var(--ready-accent)',
    audioLevel: 0,
  };
}
