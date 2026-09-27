export type ConnectionStateDTO = 'ready' | 'recording' | 'error' | 'connecting';
export type TranscriptionStateDTO = 'loadingModels' | 'idle' | 'listening' | 'transcribing';
export type SystemAudioCaptureModeDTO = 'none' | 'selectedProcess' | 'globalOutput';
export type MicrophoneInputRecoveryStateDTO = 'idle' | 'reconnecting' | 'failed';
export type WindowRetranscriptionPhaseDTO = 'running' | 'applying' | 'completed' | 'failed';
export type AudioSourceKindDTO = 'Microphone' | 'SystemAudio';

export interface TranscriptLineDTO {
  id: string;
  text: string;
  speakerId: string | null;
  isInterim: boolean;
  displayStart: string | null;
  timelineStartSeconds: number | null;
  timelineEndSeconds: number | null;
  source: AudioSourceKindDTO | null;
  lineComplete: boolean;
}

export interface TranscriptPatchDTO {
  orderedIDs: string[];
  upserts: TranscriptLineDTO[];
  removedIDs: string[];
}

export interface AudioProcessDTO {
  id: number;
  name: string;
  kind: 'process' | 'app';
  audioActive: boolean;
  bundleId: string | null;
  iconDataUrl?: string | null;
}

export interface AudioProcessGroupDTO {
  id: string;
  title: string;
  processes: AudioProcessDTO[];
}

export interface MeetingMemberDTO {
  id: string;
  source: string | null;
  isPostProcessed: boolean;
  startTime: string | null;
  durationSeconds: number | null;
  timelineOffsetSeconds: number | null;
  recordingPartIndex: number | null;
}

export interface AnalysisSummaryDTO {
  count: number;
  latestFilename: string;
  latestTimestamp: string;
  pendingActionCount: number | null;
}

export interface MeetingListItemDTO {
  id: string;
  name: string;
  purpose: string | null;
  participants: string[];
  startTime: string;
  endTime: string | null;
  durationSeconds: number | null;
  isPostProcessed: boolean;
  analysisSummary: AnalysisSummaryDTO | null;
  sessionId: string | null;
  audioSource: string | null;
  members: MeetingMemberDTO[] | null;
  formattedDate: string;
  shortFormattedDuration: string;
  relativeDateString: string;
}

export interface AnalysisMetadataEntryDTO {
  id: string;
  timestamp: string;
  filename: string;
  modes: string[];
  modelUsed: string;
  formattedDate: string;
  modesDisplay: string;
  shortModelName: string;
}

export interface ReasoningModelInfoDTO {
  id: string;
  name: string;
  displayName: string;
  provider: string;
  isApiModel: boolean;
  category: 'local' | 'api' | 'custom';
}

export interface ActionItemDTO {
  id: string;
  task: string;
  assignedTo: string | null;
  deadline: string | null;
  priority: string | null;
  context: string;
  timestamp: number;
  speaker: string | null;
}

export interface MeetingActionProposalDTO {
  id: string;
  sourceActionItemIndex: number | null;
  sourceActionItemIndexes?: number[];
  sourceTask: string;
  sourceContext: string | null;
  sourceTimestamp: number | null;
  sourceSpeaker: string | null;
  suggestedAgentTask: string;
  capabilityType: string;
  confidence: number;
  whyBasilCanHelp: string;
  missingInformation: string[];
  requiresUserConfirmation: boolean;
  executionMode?: 'todo_only' | 'agent_assisted';
  workspaceSource: string;
  executionStatus: string;
  submittedAgentTaskId: string | null;
  todoId: string | null;
  todoStatus: string | null;
  lastError: string | null;
  isEditingDraft: boolean;
  draftPrompt: string;
  liveAgentStatus: string | null;
}

export interface DecisionDTO {
  id: string;
  decision: string;
  rationale: string | null;
  decidedBy: string | null;
  timestamp: number;
  context: string;
  impact: string | null;
}

export interface QuestionAnswerDTO {
  id: string;
  question: string;
  answer: string;
  asker: string | null;
  responder: string | null;
  timestamp: number;
  context: string;
  resolved: boolean;
}

export interface SpeakerSentimentDTO {
  sentiment: string;
  engagement: string;
  keyContributions: string;
}

export interface SentimentMomentDTO {
  id: string;
  timestamp: number;
  description: string;
  context: string;
}

export interface SentimentAnalysisDTO {
  overallSentiment: string;
  sentimentScore: number;
  engagementLevel: string;
  speakerSentiments: Record<string, SpeakerSentimentDTO> | null;
  positiveMoments: SentimentMomentDTO[] | null;
  negativeMoments: SentimentMomentDTO[] | null;
  toneIndicators: string[] | null;
}

export interface AnalysisModeFailureDTO {
  id: string;
  mode: string;
  category: string;
  message: string;
  retryable: boolean;
  refusalCategory?: string | null;
  refusalExplanation?: string | null;
}

export interface AnalysisSafetyOmissionDTO {
  id: string;
  mode: string;
  startTimestamp: number;
  endTimestamp: number;
  segmentCount: number;
  provider: string;
  refusalCategory: string | null;
  refusalExplanation: string | null;
  recovery: string;
}

export interface MeetingAnalysisResultDTO {
  meetingId: string | null;
  filename: string | null;
  analyzedAt: string;
  modelUsed: string;
  fallbackModelUsed?: string | null;
  requestedModes: string[] | null;
  modesAnalyzed: string[];
  failedModes: AnalysisModeFailureDTO[] | null;
  safetyOmissions?: AnalysisSafetyOmissionDTO[] | null;
  customInstructions: string | null;
  actionItems: ActionItemDTO[] | null;
  suggestedActions: MeetingActionProposalDTO[] | null;
  summary: string | null;
  decisions: DecisionDTO[] | null;
  questionsAnswers: QuestionAnswerDTO[] | null;
  sentimentAnalysis: SentimentAnalysisDTO | null;
  customAnalysis: string | null;
  transcriptDuration: number;
  speakerCount: number;
  processingTime: number;
  meetingName: string | null;
  meetingPurpose: string | null;
  participants: string[] | null;
  formattedDuration: string;
  formattedProcessingTime: string;
  /**
   * Full transcript lines for the analyzed meeting, present whenever the
   * host already has them loaded (live analysis-complete or a selected
   * history meeting). Appended to the export/copy-all text as a legible
   * `## Transcript` section; absent (not just empty) on older backends.
   */
  transcript?: TranscriptLineDTO[] | null;
}

export interface WindowRetranscriptionStatusDTO {
  id: string;
  source: AudioSourceKindDTO;
  start: number;
  end: number;
  phase: WindowRetranscriptionPhaseDTO;
  message: string;
}

export interface TranscriptionModelInfoDTO {
  id: string;
  name: string;
  displayName: string;
  provider: string | null;
  category: 'local' | 'api' | 'custom';
}

import type { FontConfig, ThemeConfig } from '@shared/webTheme';

export interface MeetingThemePayloadDTO extends Partial<ThemeConfig> {
  [key: string]: string | undefined;
}

export interface MeetingFontPayloadDTO extends Partial<FontConfig> {
  [key: string]: string | undefined;
}

export interface MeetingUIStateDTO {
  isRecording: boolean;
  statusMessage: string;
  recordingTimeString: string;
  connectionState: ConnectionStateDTO;
  meetingName: string;
  meetingPurpose: string;
  meetingParticipants: string;
  isSystemAudioAvailable: boolean;
  availableAudioProcesses: AudioProcessGroupDTO[];
  enableMicrophone: boolean;
  systemAudioCaptureMode: SystemAudioCaptureModeDTO;
  selectedAudioProcessId: number | null;
  transcriptionState: TranscriptionStateDTO;
  accumulatedDuration: number;
  lastTriggerReason: string | null;
  availableModels: TranscriptionModelInfoDTO[];
  selectedModel: string;
  isLoadingModels: boolean;
  hasRecordedAudio: boolean;
  hasTranscription: boolean;
  isPostProcessing: boolean;
  postProcessingModel: string;
  postProcessingProgress: number;
  postProcessingStage: string;
  postProcessingMessage: string;
  postProcessingCurrentTime: number;
  postProcessingTotalTime: number;
  postProcessingETA: number;
  postProcessingSourceIndex: number;
  postProcessingSourceTotal: number;
  postProcessingAggregateProgress: number;
  postProcessingStartedAutomatically: boolean;
  activePostProcessingMeetingId: string | null;
  sessionAutoRetranscribeOnStop: boolean;
  sessionAutoRetranscribeDuringRecording: boolean;
  sessionAutoAnalyzeOnComplete: boolean;
  sessionAutoAnalyzeModes: string[];
  sessionAutoAnalyzeCustomInstructions: string;
  sessionAutoAnalyzeTiming: string;
  windowRetranscriptionStatus: WindowRetranscriptionStatusDTO | null;
  isApplyingWindowedRetranscription: boolean;
  isAnalysisSectionExpanded: boolean;
  selectedAnalysisModes: string[];
  analysisCustomInstructions: string;
  selectedAnalysisModelId: string | null;
  localAnalysisModels: ReasoningModelInfoDTO[];
  apiAnalysisModels: ReasoningModelInfoDTO[];
  useApiModelsForAnalysis: boolean;
  isLoadingAnalysisModels: boolean;
  isAnalyzing: boolean;
  analysisProgress: number;
  analysisMessage: string;
  currentAnalysisMode: string | null;
  analysisJustCompleted: boolean;
  analysisStartedAutomatically: boolean;
  activeAnalysisMeetingId: string | null;
  isLoadingAnalysisHistory: boolean;
  isLoadingAnalysisResult: boolean;
  analysisResultRequestedFilename: string | null;
  analysisResultLoadError: string | null;
  isSidebarCollapsed: boolean;
  isLoadingMeetings: boolean;
  isLoadingMoreMeetings: boolean;
  hasMoreMeetings: boolean;
  meetingHistoryLoadMoreError: string | null;
  selectedMeetingId: string | null;
  displayedMeetingWorkOwnerId: string | null;
  isViewingPastMeeting: boolean;
  meetingSearchText: string;
  meetingSearchFilters: MeetingHistorySearchFiltersDTO;
  microphoneAudioLevel: number;
  systemAudioLevel: number;
  microphoneInputRecoveryState: MicrophoneInputRecoveryStateDTO;
  microphoneInputRecoveryMessage: string | null;
}

export type MeetingSearchTermModeDTO = 'and' | 'or';

export interface MeetingHistorySearchFiltersDTO {
  queryMode: MeetingSearchTermModeDTO;
  name: string;
  nameMode: MeetingSearchTermModeDTO;
  purpose: string;
  purposeMode: MeetingSearchTermModeDTO;
  participants: string;
  participantsMode: MeetingSearchTermModeDTO;
  transcript: string;
  transcriptMode: MeetingSearchTermModeDTO;
  source: string;
  sourceMode: MeetingSearchTermModeDTO;
  startDate: string | null;
  endDate: string | null;
  processing: 'any' | 'complete' | 'incomplete';
  analysis: 'any' | 'has_analysis' | 'no_analysis';
}

export type MeetingBridgeEventType =
  | 'snapshot'
  | 'sessionDelta'
  | 'transcriptDelta'
  | 'historyDelta'
  | 'analysisHistoryDelta'
  | 'analysisResultDelta'
  | 'proposalsDelta'
  | 'themeChanged'
  | 'validationError';

export interface MeetingBridgeEvent {
  type: MeetingBridgeEventType;
  revision: number;
  selectionGeneration: number;
  protocolVersion: number;
  ui?: MeetingUIStateDTO;
  transcript?: TranscriptLineDTO[];
  transcriptPatch?: TranscriptPatchDTO;
  history?: MeetingListItemDTO[];
  analysisHistory?: AnalysisMetadataEntryDTO[];
  analysisResult?: MeetingAnalysisResultDTO;
  proposals?: MeetingActionProposalDTO[];
  theme?: MeetingThemePayloadDTO;
  fonts?: MeetingFontPayloadDTO;
  validationErrorCode?: string;
  validationErrorMessage?: string;
}

export interface MeetingMeterPayload {
  microphoneAudioLevel: number;
  systemAudioLevel: number;
}

export type MeetingBridgeIntent =
  | { type: 'reactReady'; protocolVersion: number }
  | { type: 'closeWindow' }
  | { type: 'minimizeWindow' }
  | { type: 'toggleWindowCollapse'; collapsed: boolean }
  | { type: 'chromeHeight'; height: number }
  | { type: 'toggleRecording' }
  | { type: 'startNewMeeting' }
  | { type: 'resumeMeeting' }
  | { type: 'selectMeeting'; meetingId: string }
  | { type: 'deleteMeeting'; meetingId: string }
  | { type: 'setSidebarCollapsed'; collapsed: boolean }
  | { type: 'setMeetingSearch'; text: string }
  | { type: 'setMeetingSearchFilters' } & MeetingHistorySearchFiltersDTO
  | { type: 'loadMoreMeetings' }
  | { type: 'updateMetadata'; name?: string; purpose?: string; participants?: string }
  | { type: 'setAudioSource'; enableMicrophone?: boolean; captureMode?: SystemAudioCaptureModeDTO; processId?: number }
  | { type: 'setPostProcessingModel'; model: string }
  | { type: 'startPostProcessing'; operation: 'transcribe' | 'diarize' }
  | {
      type: 'setAutomation';
      autoRetranscribeOnStop?: boolean;
      autoRetranscribeDuringRecording?: boolean;
      autoAnalyzeOnComplete?: boolean;
      autoAnalyzeModes?: string[];
      autoAnalyzeCustomInstructions?: string;
      autoAnalyzeTiming?: string;
    }
  | { type: 'setAnalysisConfiguration'; modes?: string[]; customInstructions?: string; modelId?: string; isExpanded?: boolean }
  | { type: 'startAnalysis' }
  | { type: 'viewAnalysis'; filename: string }
  | { type: 'deleteAnalysis'; filename: string }
  | { type: 'retryAnalysisModes'; filename: string; modes: string[] }
  | { type: 'copyText'; text: string; rich: boolean }
  | { type: 'exportAnalysis'; filename: string; format: 'markdown' | 'text'; text?: string; filenameSuggestion?: string }
  | { type: 'updateProposal'; proposalId: string; draftPrompt?: string; isEditingDraft?: boolean }
  | { type: 'promoteProposalToTodo'; proposalId: string }
  | { type: 'startProposalNow'; proposalId: string }
  | { type: 'openProposalTodo'; todoId: string }
  | { type: 'openProposalAgentTask'; agentTaskId: string }
  | { type: 'promoteAllProposalsToTodos' }
  | { type: 'dismissProposal'; proposalId: string }
  | { type: 'restoreProposal'; proposalId: string };
