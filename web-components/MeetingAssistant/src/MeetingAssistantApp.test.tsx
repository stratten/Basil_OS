import { act, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MeetingAssistantApp from './MeetingAssistantApp';
import type { MeetingBridgeEvent } from './bridge/types';
import { publishMeetingMeter } from './bridge/meetingMeterStore';

let capturedEventHandler: ((event: MeetingBridgeEvent) => void) | null = null;

vi.mock('./bridge/meetingBridge', () => ({
  registerEventHandler: vi.fn((cb: (event: MeetingBridgeEvent) => void) => {
    capturedEventHandler = cb;
  }),
  reportReady: vi.fn(),
  setSidebarCollapsed: vi.fn(),
  toggleWindowCollapse: vi.fn(),
  toggleRecording: vi.fn(),
  resumeMeeting: vi.fn(),
  startNewMeeting: vi.fn(),
  loadMoreMeetings: vi.fn(),
}));

vi.mock('./lib/hostAppearance', () => ({
  applyMeetingHostFonts: vi.fn(),
  applyMeetingHostTheme: vi.fn(),
}));

vi.mock('./components/WindowChrome', () => ({
  default: ({ isCollapsed, onToggleCollapse, bubble, hideWindowControls, canCollapse }: { isCollapsed: boolean; onToggleCollapse: () => void; bubble?: ReactNode; hideWindowControls?: boolean; canCollapse?: boolean }) => (
    <>
      <output data-testid="window-chrome-props">{JSON.stringify({ hideWindowControls: hideWindowControls ?? false, canCollapse: canCollapse ?? true })}</output>
      {canCollapse !== false && (
        <button type="button" onClick={onToggleCollapse}>{isCollapsed ? 'Expand' : 'Collapse'}</button>
      )}
      {bubble}
    </>
  ),
}));

vi.mock('../../AgentTaskResult/src/components/AnimatedBubble', () => ({
  default: ({ audioLevel }: { audioLevel: number }) => <output data-testid="bubble-audio-level">{audioLevel}</output>,
}));

let transcriptRenderCount = 0;
vi.mock('./components/TranscriptPanel', () => ({
  default: () => {
    transcriptRenderCount += 1;
    return <div data-testid="transcript-render-count">{transcriptRenderCount}</div>;
  },
}));

const minimalUI: MeetingBridgeEvent['ui'] = {
  isRecording: true,
  statusMessage: 'Recording',
  recordingTimeString: '00:05',
  connectionState: 'recording',
  meetingName: 'Meeting',
  meetingPurpose: '',
  meetingParticipants: '',
  isSystemAudioAvailable: false,
  availableAudioProcesses: [],
  enableMicrophone: true,
  systemAudioCaptureMode: 'none',
  selectedAudioProcessId: null,
  transcriptionState: 'listening',
  accumulatedDuration: 0,
  lastTriggerReason: null,
  availableModels: [],
  selectedModel: '',
  isLoadingModels: false,
  hasRecordedAudio: false,
  hasTranscription: false,
  isPostProcessing: false,
  postProcessingModel: '',
  postProcessingProgress: 0,
  postProcessingStage: '',
  postProcessingMessage: '',
  postProcessingCurrentTime: 0,
  postProcessingTotalTime: 0,
  postProcessingETA: 0,
  postProcessingSourceIndex: 0,
  postProcessingSourceTotal: 0,
  postProcessingAggregateProgress: 0,
  postProcessingStartedAutomatically: false,
  activePostProcessingMeetingId: null,
  sessionAutoRetranscribeOnStop: false,
  sessionAutoRetranscribeDuringRecording: false,
  sessionAutoAnalyzeOnComplete: false,
  sessionAutoAnalyzeModes: [],
  sessionAutoAnalyzeCustomInstructions: '',
  sessionAutoAnalyzeTiming: 'afterStop',
  windowRetranscriptionStatus: null,
  isApplyingWindowedRetranscription: false,
  isAnalysisSectionExpanded: false,
  selectedAnalysisModes: [],
  analysisCustomInstructions: '',
  selectedAnalysisModelId: null,
  localAnalysisModels: [],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  isLoadingAnalysisModels: false,
  isAnalyzing: false,
  analysisProgress: 0,
  analysisMessage: '',
  currentAnalysisMode: null,
  analysisJustCompleted: false,
  analysisStartedAutomatically: false,
  activeAnalysisMeetingId: null,
  isLoadingAnalysisHistory: false,
  isLoadingAnalysisResult: false,
  analysisResultRequestedFilename: null,
  analysisResultLoadError: null,
  isSidebarCollapsed: true,
  isLoadingMeetings: false,
  isLoadingMoreMeetings: false,
  hasMoreMeetings: false,
  meetingHistoryLoadMoreError: null,
  selectedMeetingId: null,
  displayedMeetingWorkOwnerId: null,
  isViewingPastMeeting: false,
  meetingSearchText: '',
  meetingSearchFilters: {
    queryMode: 'and',
    name: '', nameMode: 'and',
    purpose: '', purposeMode: 'and',
    participants: '', participantsMode: 'and',
    transcript: '', transcriptMode: 'and',
    source: '', sourceMode: 'and',
    startDate: null, endDate: null,
    processing: 'any',
    analysis: 'any',
  },
  microphoneAudioLevel: 0,
  systemAudioLevel: 0,
  microphoneInputRecoveryState: 'idle',
  microphoneInputRecoveryMessage: null,
};

describe('MeetingAssistantApp collapse retention', () => {
  it('keeps the content subtree mounted and inert while collapsed', () => {
    render(<MeetingAssistantApp />);
    const content = screen.getByText('Connecting to Meeting Assistant…');

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));

    expect(content.isConnected).toBe(true);
    expect(content).toHaveAttribute('hidden');
    expect(content).toHaveAttribute('aria-hidden', 'true');
    expect(content).toHaveAttribute('inert');

    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));

    expect(screen.getByText('Connecting to Meeting Assistant…')).toBe(content);
    expect(content).not.toHaveAttribute('hidden');
    expect(content).not.toHaveAttribute('inert');
  });
});

describe('MeetingAssistantApp meter render isolation', () => {
  it('updates only the isolated bubble from a meter frame, leaving the connected transcript subtree unrendered', () => {
    transcriptRenderCount = 0;
    capturedEventHandler = null;
    render(<MeetingAssistantApp />);

    act(() => {
      capturedEventHandler!({
        type: 'snapshot',
        revision: 0,
        selectionGeneration: 0,
        protocolVersion: 4,
        ui: minimalUI,
        transcript: [],
        history: [],
        analysisHistory: [],
        proposals: [],
      });
    });

    expect(screen.getByTestId('transcript-render-count')).toHaveTextContent('1');
    expect(screen.getByTestId('bubble-audio-level')).toHaveTextContent('0');

    act(() => {
      publishMeetingMeter({ microphoneAudioLevel: 0.8, systemAudioLevel: 0.3 });
    });

    expect(screen.getByTestId('bubble-audio-level')).toHaveTextContent('0.8');
    expect(screen.getByTestId('transcript-render-count')).toHaveTextContent('1');
  });
});

describe('MeetingAssistantApp embedded presentation', () => {
  afterEach(() => {
    delete document.documentElement.dataset.meetingAssistantEmbedded;
  });

  it('omits the standalone window chrome when the embedded marker is present at mount', () => {
    document.documentElement.dataset.meetingAssistantEmbedded = 'true';
    render(<MeetingAssistantApp />);

    expect(screen.queryByTestId('window-chrome-props')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Collapse' })).toBeNull();
    expect(document.querySelector('.basil-webkit-window-frame--embedded')).toBeTruthy();
    expect(document.querySelector('.meeting-assistant-surface--embedded')).toBeTruthy();
    expect(screen.queryByTestId('bubble-audio-level')).toBeNull();
  });

  it('keeps window controls and collapse enabled when the embedded marker is absent', () => {
    render(<MeetingAssistantApp />);

    expect(screen.getByTestId('window-chrome-props')).toHaveTextContent(
      JSON.stringify({ hideWindowControls: false, canCollapse: true }),
    );
    expect(screen.getByRole('button', { name: 'Collapse' })).toBeTruthy();
    expect(document.querySelector('.basil-webkit-window-frame--embedded')).toBeNull();
    expect(screen.getByTestId('bubble-audio-level')).toBeTruthy();
  });
});
