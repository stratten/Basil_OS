import { cloneElement, useEffect, useMemo, useState, type CSSProperties, type HTMLAttributes, type ReactElement } from 'react';
import { openCompanionWindow, setCompanionPaneExtent, setSidebarCollapsed, toggleWindowCollapse } from './bridge/meetingBridge';
import { initialMeetingState } from './state/meetingReducer';
import { useMeetingBridgeState } from './state/useMeetingBridgeState';
import WindowChrome from './components/WindowChrome';
import MeetingHistorySidebar from './components/MeetingHistorySidebar';
import MeetingMetadataForm from './components/MeetingMetadataForm';
import AudioSourceControls from './components/AudioSourceControls';
import RecordingControls from './components/RecordingControls';
import CollapsedRecordingActions from './components/CollapsedRecordingActions';
import TranscriptPanel from './components/TranscriptPanel';
import TranscriptToolsCard from './components/TranscriptToolsCard';
import AnalysisCard from './components/AnalysisCard';
import { CollapsedHistoryRail } from '../../shared/HistorySidebarControls';
import CollapsibleSidebar from '@shared/CollapsibleSidebar';
import AnimatedBubble from '../../shared/bubble/AnimatedBubble';
import { useMeetingMeter } from './bridge/meetingMeterStore';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';
import CompanionPane from './companion/CompanionPane';
import { CompanionLinksProvider, useCompanionLinksValue } from './companion/companionLinks';
import CompanionRail from './companion/CompanionRail';
import CompanionSetupPane from './companion/CompanionSetupPane';
import { COMPANION_PANE_WIDTH, COMPANION_RAIL_WIDTH } from './companion/companionLayout';
import { useEmbeddedCompanion } from './companion/useEmbeddedCompanion';

export default function MeetingAssistantApp() {
  const state = useMeetingBridgeState();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);
  const [embedded] = useState(
    () => document.documentElement.dataset.meetingAssistantEmbedded === 'true',
  );

  const ui = state.ui;

  const embeddedCompanion = useEmbeddedCompanion(ui);
  const companionExtent = embeddedCompanion.extent;
  const companionLinks = useCompanionLinksValue({
    role: 'notetaker',
    transcript: state.transcript,
    items: embeddedCompanion.companion.state.timeline.items,
    focusRequest: state.focusRequest,
    embeddedPane: { available: embeddedCompanion.kind === 'recording' && !embeddedCompanion.detached, reveal: embeddedCompanion.showPane },
  });

  // The host window grows by the Companion column's width (and shrinks back), so opening it never narrows the main column.
  useEffect(() => {
    if (!embedded) setCompanionPaneExtent(companionExtent);
  }, [embedded, companionExtent]);

  const handleToggleCollapse = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    toggleWindowCollapse(next);
  };

  useCollapseShortcut(handleToggleCollapse, !embedded);

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
          <AudioSourceControls ui={ui} companion={embeddedCompanion.switchProps} />
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
        <CollapsibleSidebar
          element="div"
          side="end"
          expanded={embeddedCompanion.expanded}
          className="companion-collapsible"
          style={{
            '--basil-sidebar-expanded-width': `${COMPANION_PANE_WIDTH}px`,
            '--basil-sidebar-collapsed-width': `${embeddedCompanion.hasRail ? COMPANION_RAIL_WIDTH : 0}px`,
          } as CSSProperties}
          collapsedContent={embeddedCompanion.hasRail ? <CompanionRail onExpand={embeddedCompanion.detached ? openCompanionWindow : embeddedCompanion.showPane} badge={embeddedCompanion.hiddenBadge} detached={embeddedCompanion.detached} /> : null}
        >
          {embeddedCompanion.renderedKind === 'setup' && (
            <CompanionSetupPane
              controller={embeddedCompanion.companion}
              globalSettings={embeddedCompanion.globalSettings}
              onClose={embeddedCompanion.hidePane}
            />
          )}
          {embeddedCompanion.renderedKind === 'recording' && (
            <CompanionPane
              ui={ui}
              controller={embeddedCompanion.companion}
              globalSettings={embeddedCompanion.globalSettings}
              isTargetRecording={embeddedCompanion.isRecording}
              variant="embedded"
              onClose={embeddedCompanion.hidePane}
            />
          )}
        </CollapsibleSidebar>
      </div>
    );
  }, [state, ui, embeddedCompanion]);

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
            collapsedActions={ui?.isRecording ? <CollapsedRecordingActions ui={ui} /> : undefined}
            bubble={<MeetingAudioBubble ui={ui} />}
            canCollapse
          />
        )}
        {/* The provider wraps the cloned element rather than sitting inside it: the hidden and inert props have to land on the content element itself, or a collapsed window keeps laying the whole body out at header height. */}
        <CompanionLinksProvider value={companionLinks}>
          {cloneElement(content, {
            hidden: isContentCollapsed,
            'aria-hidden': isContentCollapsed,
            inert: isContentCollapsed ? '' : undefined,
          })}
        </CompanionLinksProvider>
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
      baseColor: 'var(--text-tertiary)',
      accentColor: 'color-mix(in srgb, var(--text-tertiary) 45%, var(--background-primary))',
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
