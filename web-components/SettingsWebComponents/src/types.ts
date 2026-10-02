export interface AppearanceSettings {
  backgroundColorRed: number
  backgroundColorGreen: number
  backgroundColorBlue: number
  primaryColorRed: number
  primaryColorGreen: number
  primaryColorBlue: number
  secondaryColorRed: number
  secondaryColorGreen: number
  secondaryColorBlue: number
  textColorRed: number
  textColorGreen: number
  textColorBlue: number
  surfaceFinish: 'flat' | 'metal'
  processingColorRed: number
  processingColorGreen: number
  processingColorBlue: number
  processingAccentColorRed: number
  processingAccentColorGreen: number
  processingAccentColorBlue: number
  preferredFont: string
}

export type AppearanceColorFieldId = 'background' | 'primary' | 'secondary' | 'text'

export interface AppearanceColorPickerRequest {
  fieldId: AppearanceColorFieldId
  red: number
  green: number
  blue: number
}

export interface ThemePayload {
  backgroundPrimary: string
  backgroundSecondary: string
  backgroundTertiary: string
  primary: string
  secondary: string
  textPrimary: string
  textSecondary: string
  textTertiary: string
  separatorColor: string
  fieldBorder: string
  recordingBase: string
  recordingAccent: string
  processingBase: string
  processingAccent: string
  warningBase: string
  surfaceFinish?: string
}

export interface FontPayload {
  fontFamily: string
  fontFamilyMedium: string
  fontFamilyBold: string
}

export type AppearanceIntentName = 'previewDraft' | 'saveDraft' | 'cancelDraft' | 'resetDraft' | 'openColorPicker'

export interface AppearanceInitEvent {
  type: 'init'
  protocolVersion: 1
  revision: number
  settings: AppearanceSettings
  availableFonts: string[]
  theme: ThemePayload
  fonts: FontPayload
}

export interface AppearanceSnapshotEvent {
  type: 'snapshot'
  protocolVersion: 1
  revision: number
  settings: AppearanceSettings
  availableFonts: string[]
}

export interface AppearanceThemeChangedEvent {
  type: 'themeChanged'
  theme: ThemePayload
  fonts: FontPayload
}

export interface AppearanceIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export interface AppearanceColorPickedEvent extends AppearanceColorPickerRequest {
  type: 'colorPicked'
}

export type AppearanceNativeEvent =
  | AppearanceInitEvent
  | AppearanceSnapshotEvent
  | AppearanceThemeChangedEvent
  | AppearanceIntentResultEvent
  | AppearanceColorPickedEvent

export interface CustomAppearanceTheme {
  id: string
  name: string
  backgroundColorRed: number
  backgroundColorGreen: number
  backgroundColorBlue: number
  primaryColorRed: number
  primaryColorGreen: number
  primaryColorBlue: number
  secondaryColorRed: number
  secondaryColorGreen: number
  secondaryColorBlue: number
  textColorRed: number
  textColorGreen: number
  textColorBlue: number
  surfaceFinish: 'flat' | 'metal'
}

export type CustomAppearanceThemeInput = Omit<CustomAppearanceTheme, 'id'>

export type AppearanceThemesNativeEvent =
  | { type: 'init'; protocolVersion: 1; themes: CustomAppearanceTheme[] }
  | { type: 'snapshot'; themes: CustomAppearanceTheme[] }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }
  | { type: 'loadError'; message: string }

export interface HotkeyBinding {
  key: string
  modifiers: string[]
  enabled: boolean
  isDoublePress: boolean
  doublePressKey: string | null
}

export interface HotkeyRowSnapshot {
  id: string
  title: string
  subtitle: string | null
  binding: HotkeyBinding
}

export interface HotkeyInitEvent {
  type: 'init'
  protocolVersion: 1
  rows: HotkeyRowSnapshot[]
  enableMonitoringAtStartup: boolean
}

export interface HotkeySnapshotEvent {
  type: 'snapshot'
  rows: HotkeyRowSnapshot[]
  enableMonitoringAtStartup: boolean
}

export interface HotkeyLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface HotkeyCapturedEvent {
  type: 'captured'
  id: string
  binding: HotkeyBinding
}

export interface HotkeyCaptureCanceledEvent {
  type: 'captureCanceled'
  id: string
}

export interface HotkeyIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type HotkeyNativeEvent =
  | HotkeyInitEvent
  | HotkeySnapshotEvent
  | HotkeyLoadErrorEvent
  | HotkeyCapturedEvent
  | HotkeyCaptureCanceledEvent
  | HotkeyIntentResultEvent

export type ProfileFormality = 'casual' | 'professional' | 'formal'
export type ProfileTone = 'friendly' | 'business' | 'technical' | 'warm' | 'direct' | 'conversational'

export interface ProfileFields {
  fullName: string | null
  preferredName: string | null
  email: string | null
  jobTitle: string | null
  companyName: string | null
  industry: string | null
  formality: ProfileFormality | null
  tone: ProfileTone | null
  customInstructions: string | null
}

export interface ProfileInitEvent {
  type: 'init'
  protocolVersion: 1
  profile: ProfileFields
}

export interface ProfileSnapshotEvent {
  type: 'snapshot'
  profile: ProfileFields
}

export interface ProfileLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ProfileIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error' | 'canceled'
  message?: string
}

export type ProfileNativeEvent =
  | ProfileInitEvent
  | ProfileSnapshotEvent
  | ProfileLoadErrorEvent
  | ProfileIntentResultEvent

export interface MacContactsSettingsFields {
  available: boolean
  preferenceEnabled: boolean
  authorizationStatus: string
  canLookup: boolean
  detail: string | null
}

export type MacContactsSettingsNativeEvent =
  | { type: 'init'; protocolVersion: 1; fields: MacContactsSettingsFields }
  | { type: 'snapshot'; fields: MacContactsSettingsFields }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }
  | { type: 'loadError'; message: string }

export type MemorySettingField = 'memoryAfterTaskEnabled' | 'memoryDailyEnabled' | 'memoryDailyTimeLocal' | 'memoryProcessingModel'

export interface MemoryIntelligenceSettings {
  memoryAfterTaskEnabled: boolean
  memoryDailyEnabled: boolean
  memoryDailyTimeLocal: string
  memoryProcessingModel: string | null
}

export interface MemoryReasoningModelOption {
  id: string
  displayName: string
}

export interface MemoryProposal {
  id: string
  targetFileName: string
  entry: string
  why: string | null
  confidence: string | null
  createdAt: string
}

export interface MemoryDocument {
  fileName: string
  sizeBytes: number
  capBytes: number | null
  updatedAt: string | null
}

export interface MemoryIntelligenceInitEvent {
  type: 'init'
  protocolVersion: 1
  settings: MemoryIntelligenceSettings
  proposals: MemoryProposal[]
  documents: MemoryDocument[]
  availableModels: MemoryReasoningModelOption[]
}

export interface MemoryIntelligenceSnapshotEvent {
  type: 'snapshot'
  settings: MemoryIntelligenceSettings
  proposals: MemoryProposal[]
  documents: MemoryDocument[]
  availableModels: MemoryReasoningModelOption[]
}

export interface MemoryIntelligenceLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface MemoryIntelligenceIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type MemoryIntelligenceNativeEvent =
  | MemoryIntelligenceInitEvent
  | MemoryIntelligenceSnapshotEvent
  | MemoryIntelligenceLoadErrorEvent
  | MemoryIntelligenceIntentResultEvent

export type WritingExamplesContextFilter = 'all' | 'email_reply' | 'email_compose' | 'social_media' | 'document'

export interface WritingExampleStyleAttributes {
  formalityLevel: number
  avgSentenceLength: number
  greetingPatterns: string[]
  closingPatterns: string[]
  toneMarkers: string[]
  paragraphStructure: string
  styleSummary: string | null
}

export interface WritingExampleStyleProfile {
  contextType: string
  styleAttributes: WritingExampleStyleAttributes
  confidence: number
  sampleCount: number
}

export interface WritingExampleSample {
  id: string
  contextType: string
  content: string
  recipient: string | null
  createdAt: string
}

export interface WritingExamplesInitEvent {
  type: 'init'
  protocolVersion: 1
  activeFilter: WritingExamplesContextFilter
  samples: WritingExampleSample[]
  styleProfile: WritingExampleStyleProfile | null
  isLoadingSamples: boolean
}

export interface WritingExamplesSnapshotEvent {
  type: 'snapshot'
  activeFilter: WritingExamplesContextFilter
  samples: WritingExampleSample[]
  styleProfile: WritingExampleStyleProfile | null
  isLoadingSamples: boolean
}

export interface WritingExamplesLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface WritingExamplesIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error' | 'canceled'
  message?: string
}

export type WritingExamplesNativeEvent =
  | WritingExamplesInitEvent
  | WritingExamplesSnapshotEvent
  | WritingExamplesLoadErrorEvent
  | WritingExamplesIntentResultEvent

export type ModelStatusKind = 'available' | 'downloadable' | 'downloading' | 'error'

export interface ModelSummary {
  id: string
  modelType: string
  variantId: string
  name: string
  capabilities: string[]
  size: number | null
  statusKind: ModelStatusKind
  progress?: number
  errorMessage?: string
  totalDownloaded?: number
  totalSize?: number
  currentFile?: string
  filesCompleted?: number
  totalFiles?: number
}

export interface ModelProviderGroup {
  provider: string
  models: ModelSummary[]
}

export interface ModelsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoadingModels: boolean
  localVisionFallbackEnabled: boolean
  isLocalVisionFallbackModelInstalled: boolean
  reasoningFallbackEnabled: boolean
  reasoningFallbackModelId: string
  reasoningGroups: ModelProviderGroup[]
  transcriptionGroups: ModelProviderGroup[]
}

export interface ModelsSnapshotEvent {
  type: 'snapshot'
  isLoadingModels: boolean
  localVisionFallbackEnabled: boolean
  isLocalVisionFallbackModelInstalled: boolean
  reasoningFallbackEnabled: boolean
  reasoningFallbackModelId: string
  reasoningGroups: ModelProviderGroup[]
  transcriptionGroups: ModelProviderGroup[]
}

export interface ModelsDownloadLogLineEvent {
  type: 'downloadLogLine'
  modelId: string
  message: string
}

export interface ModelsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ModelsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error' | 'canceled'
  message?: string
}

export type ModelsNativeEvent =
  | ModelsInitEvent
  | ModelsSnapshotEvent
  | ModelsDownloadLogLineEvent
  | ModelsLoadErrorEvent
  | ModelsIntentResultEvent

export type BrowserSensitiveFillPolicy = 'never' | 'ask_every_time' | 'approved_domains'
export type BrowserForegroundControlPolicy = 'background_only' | 'ask_before_foreground' | 'allow_foreground_when_needed'
export type BrowserAutomationSessionMode = 'user_browser' | 'basil_automation_browser'
export type BrowserPreferredUserBrowser = 'system_default' | 'chrome' | 'edge' | 'safari'

export interface BrowserDomainApproval {
  domain: string
  createdAt: string
  lastUsed: string
  useCount: number
  allowSensitiveFill: boolean
}

export interface BrowserAutomationSettingsSnapshot {
  sensitiveFillPolicy: BrowserSensitiveFillPolicy
  foregroundControlPolicy: BrowserForegroundControlPolicy
  defaultSessionMode: BrowserAutomationSessionMode
  preferredUserBrowser: BrowserPreferredUserBrowser
  approvedSensitiveFillDomains: BrowserDomainApproval[]
  showActionHighlights: boolean
  recordBrowserActionTrace: boolean
  allowVisualFallback: boolean
}

export interface BrowserAutomationInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  settings: BrowserAutomationSettingsSnapshot | null
}

export interface BrowserAutomationSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  settings: BrowserAutomationSettingsSnapshot | null
}

export interface BrowserAutomationLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface BrowserAutomationIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type BrowserAutomationNativeEvent =
  | BrowserAutomationInitEvent
  | BrowserAutomationSnapshotEvent
  | BrowserAutomationLoadErrorEvent
  | BrowserAutomationIntentResultEvent

export type AgentTaskInputModality = 'voice' | 'text'
export type AssistantSessionInputMode = 'speak' | 'type'
export type AssistantOutputPasteMode = 'always' | 'auto' | 'never'

export interface ReasoningDefaultsModelInfo {
  id: string
  name: string
  displayName: string
  provider: string
  isApiModel: boolean
}

export interface ReasoningDefaultsSettingsSnapshot {
  localModels: ReasoningDefaultsModelInfo[]
  apiModels: ReasoningDefaultsModelInfo[]
  customModels: ReasoningDefaultsModelInfo[]
  selectedModelId: string
  useApiModels: boolean
  closeAssistantSessionOnInsert: boolean
  assistantOutputPasteMode: AssistantOutputPasteMode
  useRegionSelection: boolean
  agentTaskDefaultModality: AgentTaskInputModality
  agentTaskAutoReopenOnCompletion: boolean
  agentTaskPushToTalk: boolean
  agentTaskPushToTalkThreshold: number
  assistantSessionDefaultModality: AssistantSessionInputMode
  assistantSessionPushToTalk: boolean
  assistantSessionPushToTalkThreshold: number
  conversationDefaultConversationOnly?: boolean
}

export interface ReasoningDefaultsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  settings: ReasoningDefaultsSettingsSnapshot | null
}

export interface ReasoningDefaultsSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  settings: ReasoningDefaultsSettingsSnapshot | null
}

export interface ReasoningDefaultsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ReasoningDefaultsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type ReasoningDefaultsNativeEvent =
  | ReasoningDefaultsInitEvent
  | ReasoningDefaultsSnapshotEvent
  | ReasoningDefaultsLoadErrorEvent
  | ReasoningDefaultsIntentResultEvent

export type ProactiveSuggestionMode = 'suggestion_only' | 'auto_execute'
export type ProactiveSuggestionCapability = 'assistant_session' | 'agent_task'

export interface ProactiveSuggestionsModelInfo {
  id: string
  displayName: string
  provider: string
  isLocal: boolean
}

export interface ProactiveSuggestionsSettingsSnapshot {
  enabled: boolean
  mode: ProactiveSuggestionMode
  frequencySeconds: number
  evaluationModel: string
  selectedEvaluationModelIsUnavailable: boolean
  minimumConfidence: number
  cooldownMinutes: number
  enabledCapabilities: ProactiveSuggestionCapability[]
  autoExecuteCapabilities: ProactiveSuggestionCapability[]
  excludedAppNames: string[]
  localModels: ProactiveSuggestionsModelInfo[]
  apiModels: ProactiveSuggestionsModelInfo[]
}

export interface ProactiveSuggestionsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  settings: ProactiveSuggestionsSettingsSnapshot | null
}

export interface ProactiveSuggestionsSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  settings: ProactiveSuggestionsSettingsSnapshot | null
}

export interface ProactiveSuggestionsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ProactiveSuggestionsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type ProactiveSuggestionsNativeEvent =
  | ProactiveSuggestionsInitEvent
  | ProactiveSuggestionsSnapshotEvent
  | ProactiveSuggestionsLoadErrorEvent
  | ProactiveSuggestionsIntentResultEvent

export interface SkillCandidateSummary {
  id: string
  title: string
  whenToUse: string
  createdAt: string
  observationCount: number
}

export interface SavedSkillSummary {
  slug: string
  title: string
  whenToUse: string
  version: number
  observationCount: number
  lastUsed: string | null
  sizeBytes: number
  capBytes: number
}

export interface SkillProcessingModelOption {
  id: string
  displayName: string
}

interface SkillsSettingsFields {
  skillCandidates: SkillCandidateSummary[]
  savedSkills: SavedSkillSummary[]
  reconciliationActive: boolean
  skillAfterTaskEnabled: boolean
  skillDailyEnabled: boolean
  skillDailyTimeLocal: string
  skillProcessingModel: string | null
  skillReconciliationMinInstances: number
  availableSkillProcessingModels: SkillProcessingModelOption[]
  pendingCandidateActionIDs: string[]
  pendingSkillDeletionSlugs: string[]
  isLoadingSkillsState: boolean
  isRunningSkillsIntelligence: boolean
  statusMessage: string | null
}

export interface SkillsInitEvent extends SkillsSettingsFields {
  type: 'init'
  protocolVersion: 1
}

export interface SkillsSnapshotEvent extends SkillsSettingsFields {
  type: 'snapshot'
}

export interface SkillsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type SkillsNativeEvent =
  | SkillsInitEvent
  | SkillsSnapshotEvent
  | SkillsIntentResultEvent

export interface MemoriesSourceStat {
  kind: string
  collected: number
  awaitingCollection: number
}

export interface MemoriesStatsData {
  collected: number
  summarized: number
  awaitingSummary: number
  awaitingRetry: number
  failed: number
  awaitingCollection: number
  bySource: MemoriesSourceStat[]
}

export interface MemoriesNarrativeProgress {
  active: boolean
  total: number
  processed: number
  finalized: number
  stillOpen: number
  failed: number
  remaining: number
  etaSeconds: number | null
  lastError: string | null
  canceling: boolean | null
  analysisConcurrency: number | null
  processingStrategy: string | null
}

export interface MemoriesProcessingModelOption {
  id: string
  displayName: string
  isLocal: boolean
}

export interface MemoriesSettingsFields {
  enabledSources: string[]
  historyDays: number
  cardingEnabled: boolean
  cardingIntervalMinutes: number
  limitPerSourcePerPass: number
  narrativeEnabled: boolean
  narrativeModel: string
  narrativeMode: 'scheduled' | 'continuous'
  narrativeScheduledTime: string
  narrativeIntervalMinutes: number
  narrativeBatchSize: number
  narrativeMaxAttempts: number
  narrativeMaxRecords: number
}

export interface MemoriesInitEvent {
  type: 'init'
  protocolVersion: 1
  settings: MemoriesSettingsFields
  stats: MemoriesStatsData | null
  narrativeProgress: MemoriesNarrativeProgress | null
  availableModels: MemoriesProcessingModelOption[]
}

export interface MemoriesSnapshotEvent {
  type: 'snapshot'
  settings: MemoriesSettingsFields
  stats: MemoriesStatsData | null
  availableModels: MemoriesProcessingModelOption[]
}

export interface MemoriesProgressEvent {
  type: 'progress'
  requestId: string
  narrativeProgress: MemoriesNarrativeProgress
}

export interface MemoriesIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string | null
}

export interface MemoriesLoadErrorEvent {
  type: 'loadError'
  message: string
}

export type MemoriesNativeEvent =
  | MemoriesInitEvent
  | MemoriesSnapshotEvent
  | MemoriesProgressEvent
  | MemoriesIntentResultEvent
  | MemoriesLoadErrorEvent

export type ActivityCaptureProcessingMode = 'realtime' | 'scheduled'

export interface ActivityCaptureModelOption {
  id: string
  displayName: string
  provider: string
  isLocal: boolean
}

export interface ActivityCaptureAppOption {
  bundleId: string
  name: string
  iconDataUrl: string | null
}

export interface ActivityCaptureSettingsFields {
  enabled: boolean
  frequencySeconds: 30 | 60 | 120 | 300 | 600
  idleThresholdSeconds: number
  postWakeGraceSeconds: number
  excludedBundleIds: string[]
  processingModel: string
  processingMode: ActivityCaptureProcessingMode
  scheduledProcessingTime: string
  processingMaxRecords: number
  autoCleanupEnabled: boolean
  retentionDays: number
  cleanupHour: number
  cleanupMinute: number
  maxStorageMb: number
}

export interface ActivityCaptureStatusFields {
  isSchedulerRunning: boolean
  nextCaptureTime: string | null
  todaysCaptures: number
  totalCapturesLast7Days: number
  totalCapturesLast30Days: number
  pendingCaptures: number
  failedCaptures: number
  skippedCaptureCount: number
  compactedCaptureCount: number
  lastPolicyDecision: string | null
}

export interface ActivityCaptureStatsFields {
  totalFiles: number
  totalSizeBytes: number
  filesLast7Days: number
  filesLast30Days: number
}

export interface ActivityCaptureProcessingProgress {
  active: boolean
  total: number
  processed: number
  succeeded: number
  failed: number
  remaining: number
  etaSeconds: number | null
  cancelRequested: boolean
  processingStrategy: string | null
  analysisConcurrency: number | null
}

export type ActivityCaptureNativeEvent =
  | {
    type: 'init'
    protocolVersion: 1
    settings: ActivityCaptureSettingsFields
    status: ActivityCaptureStatusFields
    stats: ActivityCaptureStatsFields | null
    processingProgress: ActivityCaptureProcessingProgress | null
    availableModels: ActivityCaptureModelOption[]
    availableApps: ActivityCaptureAppOption[]
    excludedApps: ActivityCaptureAppOption[]
    retentionDayOptions: number[]
    maxStorageOptions: number[]
  }
  | {
    type: 'snapshot'
    settings: ActivityCaptureSettingsFields
    stats: ActivityCaptureStatsFields | null
    availableModels: ActivityCaptureModelOption[]
    excludedApps: ActivityCaptureAppOption[]
  }
  | { type: 'status'; status: ActivityCaptureStatusFields }
  | { type: 'progress'; requestId?: string; processingProgress: ActivityCaptureProcessingProgress | null }
  | { type: 'availableApps'; availableApps: ActivityCaptureAppOption[] }
  | { type: 'searchAppsResults'; requestId: string; apps: ActivityCaptureAppOption[] }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error' | 'canceled'; message?: string }
  | { type: 'loadError'; message: string }

export interface MeetingDetectionAppOption {
  bundleId: string
  name: string
  iconDataUrl: string | null
}

export interface MeetingDetectionSettingsFields {
  enabled: boolean
  mode: 'prompt' | 'auto_start'
  pollSeconds: number
  excludedBundleIds: string[]
  excludedAppNames: string[]
  cooldownMinutes: number
  useCalendarEnrichment: boolean
  requireCalendarMatch: boolean
  autoEnd: boolean
  inactivityTimeoutMinutes: number
}

export type MeetingDetectionNativeEvent =
  | {
    type: 'init'
    protocolVersion: 1
    settings: MeetingDetectionSettingsFields
    availableApps: MeetingDetectionAppOption[]
    excludedApps: MeetingDetectionAppOption[]
    requiredBundleIds: string[]
  }
  | {
    type: 'snapshot'
    settings: MeetingDetectionSettingsFields
    excludedApps: MeetingDetectionAppOption[]
    requiredBundleIds: string[]
  }
  | { type: 'availableApps'; availableApps: MeetingDetectionAppOption[] }
  | { type: 'searchAppsResults'; requestId: string; apps: MeetingDetectionAppOption[] }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }
  | { type: 'loadError'; message: string }

export interface MeetingAutomationAnalysisModeOption {
  id: string
  label: string
}

export interface MeetingAutomationSettingsFields {
  liveTranscriptionByDefault: boolean
  autoRetranscribeOnStop: boolean
  autoRetranscribeDuringRecording: boolean
  retranscribeWindowMinutes: number
  autoAnalyzeOnComplete: boolean
  autoAnalyzeModes: string[]
  autoAnalyzeCustomInstructions: string
  autoAnalyzeTiming: 'after' | 'before'
}

export type MeetingAutomationNativeEvent =
  | {
    type: 'init'
    protocolVersion: 1
    settings: MeetingAutomationSettingsFields
    analysisModes: MeetingAutomationAnalysisModeOption[]
  }
  | { type: 'snapshot'; settings: MeetingAutomationSettingsFields }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }
  | { type: 'loadError'; message: string }

export type DateDisplayStyle = 'relative' | 'absolute'

export type DateTimeNativeEvent =
  | { type: 'init'; protocolVersion: 1; dateDisplayStyle: DateDisplayStyle }
  | { type: 'snapshot'; dateDisplayStyle: DateDisplayStyle }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }
  | { type: 'loadError'; message: string }

export interface HomeReasoningModelOption {
  id: string
  name: string
  displayName: string
  provider: string
  isApiModel: boolean
}

export interface HomeTranscriptionModelOption {
  id: string
  displayName: string
  isApiModel: boolean
  provider?: string
}

export type HomeQuickToggleField =
  | 'enableMonitoringAtStartup'
  | 'enableVoiceListenerAtStartup'
  | 'startActivityCaptureAtLaunch'
  | 'startMeetingDetectionAtLaunch'
  | 'activityCaptureEnabled'
  | 'meetingDetectionEnabled'
  | 'proactiveSuggestionsEnabled'

export interface HomeSettingsFields {
  setupAssistantPending: boolean
  setupAssistantStateAvailable: boolean
  permissionsGrantedCount: number
  permissionsTotalCount: number
  enableMonitoringAtStartup: boolean
  enableVoiceListenerAtStartup: boolean
  startActivityCaptureAtLaunch: boolean
  startMeetingDetectionAtLaunch: boolean
  backgroundBehaviorAvailable: boolean
  activityCaptureEnabled: boolean
  activityCaptureAvailable: boolean
  meetingDetectionEnabled: boolean
  meetingDetectionAvailable: boolean
  proactiveSuggestionsEnabled: boolean
  proactiveSuggestionsAvailable: boolean
  localModels: HomeReasoningModelOption[]
  apiModels: HomeReasoningModelOption[]
  customModels: HomeReasoningModelOption[]
  selectedModelId: string
  useApiModels: boolean
  reasoningModelsAvailable: boolean
  localTranscriptionModels: HomeTranscriptionModelOption[]
  apiTranscriptionModels: HomeTranscriptionModelOption[]
  selectedTranscriptionModelId: string
  transcriptionModelsAvailable: boolean
}

export interface HomeInitEvent {
  type: 'init'
  protocolVersion: 1
  fields: HomeSettingsFields
}

export interface HomeSnapshotEvent {
  type: 'snapshot'
  fields: HomeSettingsFields
}

export interface HomeLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface HomeIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type HomeNativeEvent =
  | HomeInitEvent
  | HomeSnapshotEvent
  | HomeLoadErrorEvent
  | HomeIntentResultEvent

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        basilAppearanceSettingsBridge?: { postMessage: any }
        basilHotkeySettingsBridge?: { postMessage: any }
        basilDateTimeSettingsBridge?: { postMessage: any }
        basilAppearanceThemesBridge?: { postMessage: any }
        basilProfileSettingsBridge?: { postMessage: any }
        basilMacContactsSettingsBridge?: { postMessage: any }
        basilMemoryIntelligenceSettingsBridge?: { postMessage: any }
        basilWritingExamplesSettingsBridge?: { postMessage: any }
        basilModelsSettingsBridge?: { postMessage: any }
        basilTranscriptionApiModelsBridge?: { postMessage: any }
        basilReasoningApiModelsBridge?: { postMessage: any }
        basilCustomModelsBridge?: { postMessage: any }
        basilBrowserAutomationSettingsBridge?: { postMessage: any }
        basilReasoningDefaultsSettingsBridge?: { postMessage: any }
        basilSkillsSettingsBridge?: { postMessage: any }
        basilMemoriesSettingsBridge?: { postMessage: any }
        basilProactiveSuggestionsSettingsBridge?: { postMessage: any }
        basilActivityCaptureSettingsBridge?: { postMessage: any }
        basilMeetingDetectionSettingsBridge?: { postMessage: any }
        basilMeetingAutomationSettingsBridge?: { postMessage: any }
        basilAccountSettingsBridge?: { postMessage: any }
        basilTranscriptionSettingsBridge?: { postMessage: any }
        basilTranscriptionHistoryBridge?: { postMessage: any }
        basilPermissionsApplicationBridge?: { postMessage: any }
        basilPermissionsCommandSecurityBridge?: { postMessage: any }
        basilConnectionsSettingsBridge?: { postMessage: any }
        basilSettingsShellBridge?: { postMessage: any }
        basilHomeSettingsBridge?: { postMessage: any }
      }
    }
  }
}

export interface TranscriptionApiModelSummary {
  id: string
  displayName: string
  description: string
  enabled: boolean
}

export interface TranscriptionApiModelsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  useApiTranscriptionModels: boolean
  openaiEnabled: boolean
  openaiHasKey: boolean
  models: TranscriptionApiModelSummary[]
}

export interface TranscriptionApiModelsSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  useApiTranscriptionModels: boolean
  openaiEnabled: boolean
  openaiHasKey: boolean
  models: TranscriptionApiModelSummary[]
}

export interface TranscriptionApiModelsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface TranscriptionApiModelsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type TranscriptionApiModelsNativeEvent =
  | TranscriptionApiModelsInitEvent
  | TranscriptionApiModelsSnapshotEvent
  | TranscriptionApiModelsLoadErrorEvent
  | TranscriptionApiModelsIntentResultEvent

export interface ReasoningApiModelSummary {
  id: string
  name: string
  description: string
  capabilities: string[]
  supportsExtendedThinking: boolean
  enabled: boolean
}

export interface ReasoningApiProviderSummary {
  id: string
  name: string
  enabled: boolean
  usingOwnApiKey: boolean
  hasKey: boolean
  models: ReasoningApiModelSummary[]
}

export interface ReasoningApiModelsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  useApiModels: boolean
  providers: ReasoningApiProviderSummary[]
}

export interface ReasoningApiModelsSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  useApiModels: boolean
  providers: ReasoningApiProviderSummary[]
}

export interface ReasoningApiModelsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ReasoningApiModelsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type ReasoningApiModelsNativeEvent =
  | ReasoningApiModelsInitEvent
  | ReasoningApiModelsSnapshotEvent
  | ReasoningApiModelsLoadErrorEvent
  | ReasoningApiModelsIntentResultEvent

export interface CustomModelSummary {
  modelId: string
  displayName: string
  handler: string
  isLocal: boolean
  baseUrl: string | null
  modelIdentifier: string | null
  modelPath: string | null
  downloadUrl: string | null
  contextWindow: number
  maxOutputTokens: number
  requiresAuth: boolean
  capabilities: string[]
  features: string[]
  toolRendering: string | null
  toolCallFormat: string | null
  description: string | null
  fileSize: number | null
  fileSizeHuman: string | null
  needsDownload: boolean
  downloadProgress?: number
  downloadStatus?: string
}

export interface HFFileSummary {
  name: string
  sizeBytes: number | null
  sizeHuman: string | null
}

export interface HFModelMetadataSummary {
  contextWindow: number | null
  modelType: string | null
  architecture: string | null
}

export interface CustomModelsInitEvent {
  type: 'init'
  protocolVersion: 1
  isLoading: boolean
  models: CustomModelSummary[]
}

export interface CustomModelsSnapshotEvent {
  type: 'snapshot'
  isLoading: boolean
  models: CustomModelSummary[]
}

export interface CustomModelsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface CustomModelsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export interface CustomModelsHFProbeResultEvent {
  type: 'hfProbeResult'
  requestId: string
  repoId: string
  ggufFiles: HFFileSummary[]
  modelMetadata: HFModelMetadataSummary | null
  error: string | null
}

export interface CustomModelsGGUFMetadataResultEvent {
  type: 'ggufMetadataResult'
  requestId: string
  success: boolean
  contextWindow: number | null
  architecture: string | null
  modelName: string | null
  error: string | null
}

export interface CustomModelsLocalFilePickedEvent {
  type: 'localFilePicked'
  requestId: string
  path: string
}

export interface CustomModelsLocalFilePickErrorEvent {
  type: 'localFilePickError'
  requestId: string
  message: string
}

export interface CustomModelsConnectionTestResultEvent {
  type: 'connectionTestResult'
  requestId: string
  success: boolean
  message: string
}

export interface CustomModelsDownloadProgressEvent {
  type: 'downloadProgress'
  modelId: string
  progress: number
  status: string
}

export type CustomModelsNativeEvent =
  | CustomModelsInitEvent
  | CustomModelsSnapshotEvent
  | CustomModelsLoadErrorEvent
  | CustomModelsIntentResultEvent
  | CustomModelsHFProbeResultEvent
  | CustomModelsGGUFMetadataResultEvent
  | CustomModelsLocalFilePickedEvent
  | CustomModelsLocalFilePickErrorEvent
  | CustomModelsConnectionTestResultEvent
  | CustomModelsDownloadProgressEvent

export type ApiKeyPreference = 'basil_cloud' | 'app_keys' | 'trial' | 'own_keys' | 'local'

export interface AccountUsageByModelEntry {
  model: string
  costUsd: number
}

export interface AccountSettingsFields {
  isAuthenticated: boolean
  userEmail: string
  subscriptionStatus: string
  hasPaymentMethod: boolean
  cardBrand: string
  cardLast4: string
  cardExpiration: string
  apiKeyPreference: ApiKeyPreference
  basilCloudSelected: boolean
  basilCloudBadge: string
  basilCloudDescription: string
  isLoadingUsage: boolean
  currentPeriodFormatted: string
  totalCostFormatted: string
  totalTokensFormatted: string
  usageByModel: AccountUsageByModelEntry[]
}

export interface AccountInitEvent extends AccountSettingsFields {
  type: 'init'
  protocolVersion: 1
}

export interface AccountSnapshotEvent extends AccountSettingsFields {
  type: 'snapshot'
}

export interface AccountIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export interface AccountLoadErrorEvent {
  type: 'loadError'
  message: string
}

export type AccountNativeEvent =
  | AccountInitEvent
  | AccountSnapshotEvent
  | AccountIntentResultEvent
  | AccountLoadErrorEvent

export interface TranscriptionModelOptionFields {
  id: string
  displayName: string
  isApiModel: boolean
  provider: string | null
}

export interface TranscriptionUnloadDelayOption {
  seconds: number
  label: string
}

export interface TranscriptionTextReplacementFields {
  source: string
  replacement: string
}

export interface TranscriptionSettingsFields {
  selectedModel: string
  apiModels: TranscriptionModelOptionFields[]
  localModels: TranscriptionModelOptionFields[]
  unloadDelaySeconds: number
  autoPasteTranscription: boolean
  autoCloseOnPaste: boolean
  startMeetingDetectionAtStartup: boolean
  enablePushToTalk: boolean
  pushToTalkThresholdMs: number
  textReplacements: TranscriptionTextReplacementFields[]
}

export interface TranscriptionSettingsInitEvent {
  type: 'init'
  protocolVersion: 1
  settings: TranscriptionSettingsFields
  unloadDelayOptions: TranscriptionUnloadDelayOption[]
}

export interface TranscriptionSettingsSnapshotEvent {
  type: 'snapshot'
  settings: TranscriptionSettingsFields
}

export interface TranscriptionSettingsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export interface TranscriptionSettingsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export type TranscriptionSettingsNativeEvent =
  | TranscriptionSettingsInitEvent
  | TranscriptionSettingsSnapshotEvent
  | TranscriptionSettingsIntentResultEvent
  | TranscriptionSettingsLoadErrorEvent

export type TranscriptionRecordStatus = 'pending' | 'completed' | 'failed'

export interface TranscriptionRecordFields {
  id: string
  formattedDate: string
  formattedLastTranscribedDate: string | null
  formattedDuration: string
  displayText: string
  modelName: string
  status: TranscriptionRecordStatus
  errorMessage: string | null
}

export type TranscriptionHistoryTimeFrameId = 'day' | 'week' | 'month' | 'all'

export interface TranscriptionHistoryTimeFrameOption {
  id: TranscriptionHistoryTimeFrameId
  label: string
}

export interface TranscriptionHistoryFields {
  isLoading: boolean
  error: string | null
  timeFrameId: TranscriptionHistoryTimeFrameId
  searchText: string
  currentlyPlayingId: string | null
  activeRetranscriptionId: string | null
  retranscriptionProgressMessage: string | null
  retranscriptionProgressFraction: number | null
  currentGlobalTranscriptionModelId: string
  availableRetranscriptionModels: TranscriptionModelOptionFields[]
  transcriptions: TranscriptionRecordFields[]
}

export interface TranscriptionHistoryInitEvent extends TranscriptionHistoryFields {
  type: 'init'
  protocolVersion: 1
  timeFrameOptions: TranscriptionHistoryTimeFrameOption[]
}

export interface TranscriptionHistorySnapshotEvent extends TranscriptionHistoryFields {
  type: 'snapshot'
}

export interface TranscriptionHistoryIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export interface TranscriptionHistoryLoadErrorEvent {
  type: 'loadError'
  message: string
}

export type TranscriptionHistoryNativeEvent =
  | TranscriptionHistoryInitEvent
  | TranscriptionHistorySnapshotEvent
  | TranscriptionHistoryIntentResultEvent
  | TranscriptionHistoryLoadErrorEvent

export type PermissionKind = 'microphone' | 'accessibility' | 'input_monitoring' | 'screen_recording' | 'apple_events'
export type PermissionStatusValue = 'granted' | 'denied' | 'not_determined' | 'unknown'

export interface PermissionsApplicationStatusMap {
  microphone: PermissionStatusValue
  accessibility: PermissionStatusValue
  inputMonitoring: PermissionStatusValue
  screenRecording: PermissionStatusValue
  appleEvents: PermissionStatusValue
}

export interface PermissionsApplicationInitEvent {
  type: 'init'
  protocolVersion: 1
  permissions: PermissionsApplicationStatusMap
}

export interface PermissionsApplicationSnapshotEvent {
  type: 'snapshot'
  permissions: PermissionsApplicationStatusMap
}

export interface PermissionsApplicationIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error'
  message?: string
}

export type PermissionsApplicationNativeEvent =
  | PermissionsApplicationInitEvent
  | PermissionsApplicationSnapshotEvent
  | PermissionsApplicationIntentResultEvent

export type ApprovalMode = 'always_approve' | 'whitelist_only' | 'always_prompt'
export type ApprovalTimeoutBehavior = 'wait_forever' | 'deny_on_timeout' | 'retry_alternative'

export interface ApprovalSettingsFields {
  approvalMode: ApprovalMode
  showFullCommandInPrompt: boolean
  rememberChoiceOption: boolean
  autoApproveReadOnly: boolean
  blockDangerousPatterns: boolean
  whitelistedCount: number
  safeExecutionMode: boolean
  approvalTimeoutSeconds: number
  timeoutBehavior: ApprovalTimeoutBehavior
}

export interface WhitelistPatternFields {
  id: string
  pattern: string
  patternType: string
  description: string
  addedDate: string | null
  lastUsed: string | null
  useCount: number
  riskLevel: string
}

export interface PermissionsCommandSecurityFields {
  isLoading: boolean
  error: string | null
  approvalSettings: ApprovalSettingsFields | null
  whitelistPatterns: WhitelistPatternFields[]
}

export interface PermissionsCommandSecurityInitEvent extends PermissionsCommandSecurityFields {
  type: 'init'
  protocolVersion: 1
}

export interface PermissionsCommandSecuritySnapshotEvent extends PermissionsCommandSecurityFields {
  type: 'snapshot'
}

export interface PermissionsCommandSecurityIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error' | 'canceled'
  message?: string
}

export interface PermissionsCommandSecurityLoadErrorEvent {
  type: 'loadError'
  message: string
}

export type PermissionsCommandSecurityNativeEvent =
  | PermissionsCommandSecurityInitEvent
  | PermissionsCommandSecuritySnapshotEvent
  | PermissionsCommandSecurityIntentResultEvent
  | PermissionsCommandSecurityLoadErrorEvent

export interface ApprovalSettingsPatch {
  approvalMode?: ApprovalMode
  safeExecutionMode?: boolean
  autoApproveReadOnly?: boolean
  blockDangerousPatterns?: boolean
  approvalTimeoutSeconds?: number
  timeoutBehavior?: ApprovalTimeoutBehavior
}

export interface MCPStarterServer {
  id: string
  friendlyName: string
  serverUrl: string
  description: string
}

export interface MCPConnectionTool {
  name: string
  description: string | null
  isReadOnlyHint: boolean
  policy: string
}

export type MCPConnectionAuthKind = 'oauth' | 'slack' | 'github_device' | 'manual_token'

export interface MCPConnection {
  id: string
  friendlyName: string
  description: string | null
  serverUrl: string
  enabled: boolean
  registeredAt: string
  lastToolRefreshAt: string | null
  lastConnectionCheckAt: string | null
  lastConnectionStatus: string | null
  lastConnectionStatusMessage: string | null
  serverName: string | null
  serverInstructions: string | null
  authKind: MCPConnectionAuthKind
  tools: MCPConnectionTool[]
}

export interface MCPCallLogEntry {
  id: string
  connectionId: string
  serverUrl: string
  toolName: string
  resultClassification: string
  errorKind: string | null
  errorMessage: string | null
  contentPreview: string | null
  startedAt: string
  completedAt: string | null
}

export interface GitHubDeviceFlowState {
  deviceCode: string
  userCode: string
  verificationUri: string
  expiresIn: number
  interval: number
  requestedScopes: string[]
}

export interface ProviderProfileWorkspaceGrant {
  id: string
  canonicalWorkspaceRoot: string
  status: string
  workspaceLabel: string
  description: string | null
  routingHints: string[]
  revision: number
}

export interface ProviderProfileSummary {
  id: string
  displayName: string
  status: string
  capabilityState: string
  description: string | null
  routingHints: string[]
  revision: number
  hasObservedCapabilities: boolean
  activeWorkspaceGrants: ProviderProfileWorkspaceGrant[]
  isStructurallyValid: boolean
  validationError: string | null
  createdAt: string
  updatedAt: string
}

export interface ProviderProfileConfiguration extends ProviderProfileSummary {
  launchArgv: string[]
  environmentAllowlist: string[]
  authenticationMethodId: string | null
}

export interface ConnectionsSettingsFields {
  starterServers: MCPStarterServer[]
  connections: MCPConnection[]
  callLogEntries: MCPCallLogEntry[]
  isLoading: boolean
  isAddingConnection: boolean
  isLoadingCallLog: boolean
  errorMessage: string | null
  statusMessage: string | null
  pendingFlowFriendlyName: string | null
  githubDeviceFlow: GitHubDeviceFlowState | null
  isPollingGitHubDeviceFlow: boolean
  providerProfiles: ProviderProfileSummary[]
  isLoadingProviderProfiles: boolean
  isMutatingProviderProfiles: boolean
  providerProfilesStatusMessage: string | null
  providerProfilesErrorMessage: string | null
}

export interface ConnectionsInitEvent extends ConnectionsSettingsFields {
  type: 'init'
  protocolVersion: 1
}

export interface ConnectionsSnapshotEvent extends ConnectionsSettingsFields {
  type: 'snapshot'
}

export interface ConnectionsIntentResultEvent {
  type: 'intentResult'
  requestId: string
  status: 'success' | 'error' | 'canceled'
  message?: string
}

export interface ConnectionsLoadErrorEvent {
  type: 'loadError'
  message: string
}

export interface ConnectionsProviderProfileConfigurationEvent {
  type: 'providerProfileConfiguration'
  requestId: string
  configuration: ProviderProfileConfiguration | null
  errorMessage?: string
}

export interface ConnectionsWorkspaceFolderChosenEvent {
  type: 'workspaceFolderChosen'
  requestId: string
  profileId: string
  canonicalWorkspaceRoot: string | null
  errorMessage?: string
}

export type ConnectionsNativeEvent =
  | ConnectionsInitEvent
  | ConnectionsSnapshotEvent
  | ConnectionsIntentResultEvent
  | ConnectionsLoadErrorEvent
  | ConnectionsProviderProfileConfigurationEvent
  | ConnectionsWorkspaceFolderChosenEvent

