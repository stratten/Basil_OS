import Foundation

// MARK: - Protocol version

/// Bump this whenever a DTO shape changes in a way that is not purely
/// additive-optional. React reports the version it was built against in
/// `reactReady`; Swift never sends a snapshot to a mismatched React build in
/// automated tests, and logs (does not crash) on a runtime mismatch since the
/// asset bundle and the app ship together.
let meetingBridgeProtocolVersion = 4

// MARK: - Transcript

struct TranscriptLineDTO: Codable, Equatable, Identifiable {
    var id: String
    var text: String
    var speakerId: String?
    var isInterim: Bool
    var displayStart: String?
    var timelineStartSeconds: Double?
    var timelineEndSeconds: Double?
    var source: String? // "Microphone" | "SystemAudio"
    var lineComplete: Bool
}

struct TranscriptPatchDTO: Codable, Equatable {
    var orderedIDs: [String]
    var upserts: [TranscriptLineDTO]
    var removedIDs: [String]

    var isEmpty: Bool {
        orderedIDs.isEmpty && upserts.isEmpty && removedIDs.isEmpty
    }
}

// MARK: - Audio processes

struct AudioProcessDTO: Codable, Equatable, Identifiable {
    var id: Int32
    var name: String
    var kind: String // "process" | "app"
    var audioActive: Bool
    var bundleId: String?
    var iconDataUrl: String? = nil
}

struct AudioProcessGroupDTO: Codable, Equatable, Identifiable {
    var id: String
    var title: String
    var processes: [AudioProcessDTO]
}

// MARK: - Meeting history

struct MeetingMemberDTO: Codable, Equatable, Identifiable {
    var id: String
    var source: String?
    var isPostProcessed: Bool
    var startTime: String?
    var durationSeconds: Double?
    var timelineOffsetSeconds: Double?
    var recordingPartIndex: Int?
}

struct AnalysisSummaryDTO: Codable, Equatable {
    var count: Int
    var latestFilename: String
    var latestTimestamp: String
    var pendingActionCount: Int?
}

struct MeetingHistorySearchFiltersDTO: Codable, Equatable {
    var queryMode: String
    var name: String
    var nameMode: String
    var purpose: String
    var purposeMode: String
    var participants: String
    var participantsMode: String
    var transcript: String
    var transcriptMode: String
    var source: String
    var sourceMode: String
    var startDate: String?
    var endDate: String?
    var processing: String
    var analysis: String
}

struct MeetingListItemDTO: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var purpose: String?
    var participants: [String]
    var startTime: String
    var endTime: String?
    var durationSeconds: Double?
    var isPostProcessed: Bool
    var analysisSummary: AnalysisSummaryDTO?
    var sessionId: String?
    var audioSource: String?
    var members: [MeetingMemberDTO]?
    var formattedDate: String
    var shortFormattedDuration: String
    var relativeDateString: String
}

struct AnalysisMetadataEntryDTO: Codable, Equatable, Identifiable {
    var id: String { filename }
    var timestamp: String
    var filename: String
    var modes: [String]
    var modelUsed: String
    var formattedDate: String
    var modesDisplay: String
    var shortModelName: String
}

// MARK: - Analysis models

struct ReasoningModelInfoDTO: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var displayName: String
    var provider: String
    var isApiModel: Bool
    var category: String
}

struct TranscriptionModelInfoDTO: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var displayName: String
    var provider: String?
    var category: String
}

// MARK: - Analysis result

struct ActionItemDTO: Codable, Equatable, Identifiable {
    var id: String
    var task: String
    var assignedTo: String?
    var deadline: String?
    var priority: String?
    var context: String
    var timestamp: Double
    var speaker: String?
}

struct MeetingActionProposalDTO: Codable, Equatable, Identifiable {
    var id: String
    var sourceActionItemIndex: Int?
    var sourceActionItemIndexes: [Int]?
    var sourceTask: String
    var sourceContext: String?
    var sourceTimestamp: Double?
    var sourceSpeaker: String?
    var suggestedAgentTask: String
    var capabilityType: String
    var confidence: Double
    var whyBasilCanHelp: String
    var missingInformation: [String]
    var requiresUserConfirmation: Bool
    var executionMode: String?
    var workspaceSource: String
    /// Effective status: local override (`MeetingActionProposalStore.statuses`)
    /// if present, else the persisted `executionStatus`. React never computes
    /// this itself; Swift always resolves the override before serializing.
    var executionStatus: String
    var submittedAgentTaskId: String?
    var todoId: String?
    var todoStatus: String?
    /// Present only while `MeetingActionProposalStore.errors[id]` is non-nil.
    var lastError: String?
    /// Present only while `MeetingActionProposalStore.editingIds` contains
    /// this id. React uses it purely to decide whether to show its own
    /// local draft textarea; the draft text itself stays in React state and
    /// is sent back only on submit via `updateProposal`.
    var isEditingDraft: Bool
    /// Mirrors `MeetingActionProposalStore.drafts[id]`, seeded once when the
    /// proposal snapshot is built and re-sent only if Swift's stored draft
    /// changes (e.g. after a `restore`). React owns further keystroke-level
    /// edits locally until it sends `updateProposal`.
    var draftPrompt: String
    /// Mirrors `MeetingActionProposalStore.liveStatuses[id]?.rawValue`, e.g.
    /// "processing", "completed", "failed", "awaiting_input". Nil when no
    /// delegated agent task has reported a live status yet.
    var liveAgentStatus: String?

    init(
        id: String,
        sourceActionItemIndex: Int?,
        sourceActionItemIndexes: [Int]? = nil,
        sourceTask: String,
        sourceContext: String?,
        sourceTimestamp: Double?,
        sourceSpeaker: String?,
        suggestedAgentTask: String,
        capabilityType: String,
        confidence: Double,
        whyBasilCanHelp: String,
        missingInformation: [String],
        requiresUserConfirmation: Bool,
        executionMode: String? = nil,
        workspaceSource: String,
        executionStatus: String,
        submittedAgentTaskId: String?,
        todoId: String?,
        todoStatus: String?,
        lastError: String?,
        isEditingDraft: Bool,
        draftPrompt: String,
        liveAgentStatus: String?
    ) {
        self.id = id
        self.sourceActionItemIndex = sourceActionItemIndex
        self.sourceActionItemIndexes = sourceActionItemIndexes
        self.sourceTask = sourceTask
        self.sourceContext = sourceContext
        self.sourceTimestamp = sourceTimestamp
        self.sourceSpeaker = sourceSpeaker
        self.suggestedAgentTask = suggestedAgentTask
        self.capabilityType = capabilityType
        self.confidence = confidence
        self.whyBasilCanHelp = whyBasilCanHelp
        self.missingInformation = missingInformation
        self.requiresUserConfirmation = requiresUserConfirmation
        self.executionMode = executionMode
        self.workspaceSource = workspaceSource
        self.executionStatus = executionStatus
        self.submittedAgentTaskId = submittedAgentTaskId
        self.todoId = todoId
        self.todoStatus = todoStatus
        self.lastError = lastError
        self.isEditingDraft = isEditingDraft
        self.draftPrompt = draftPrompt
        self.liveAgentStatus = liveAgentStatus
    }
}

struct DecisionDTO: Codable, Equatable, Identifiable {
    var id: String
    var decision: String
    var rationale: String?
    var decidedBy: String?
    var timestamp: Double
    var context: String
    var impact: String?
}

struct QuestionAnswerDTO: Codable, Equatable, Identifiable {
    var id: String
    var question: String
    var answer: String
    var asker: String?
    var responder: String?
    var timestamp: Double
    var context: String
    var resolved: Bool
}

struct SpeakerSentimentDTO: Codable, Equatable {
    var sentiment: String
    var engagement: String
    var keyContributions: String
}

struct SentimentMomentDTO: Codable, Equatable, Identifiable {
    var id: String
    var timestamp: Double
    var description: String
    var context: String
}

struct SentimentAnalysisDTO: Codable, Equatable {
    var overallSentiment: String
    var sentimentScore: Double
    var engagementLevel: String
    var speakerSentiments: [String: SpeakerSentimentDTO]?
    var positiveMoments: [SentimentMomentDTO]?
    var negativeMoments: [SentimentMomentDTO]?
    var toneIndicators: [String]?
}

struct AnalysisSafetyOmissionDTO: Codable, Equatable, Identifiable {
    var id: String { "\(mode)-\(startTimestamp)-\(endTimestamp)-\(recovery)" }
    var mode: String
    var startTimestamp: Double
    var endTimestamp: Double
    var segmentCount: Int
    var provider: String
    var refusalCategory: String?
    var refusalExplanation: String?
    var recovery: String
}

struct AnalysisModeFailureDTO: Codable, Equatable, Identifiable {
    var id: String { mode }
    var mode: String
    var category: String
    var message: String
    var retryable: Bool
    var refusalCategory: String?
    var refusalExplanation: String?
}

struct MeetingAnalysisResultDTO: Codable, Equatable {
    var meetingId: String?
    var filename: String?
    var analyzedAt: String
    var modelUsed: String
    var requestedModes: [String]?
    var modesAnalyzed: [String]
    var failedModes: [AnalysisModeFailureDTO]?
    var safetyOmissions: [AnalysisSafetyOmissionDTO]?
    var customInstructions: String?
    var actionItems: [ActionItemDTO]?
    var suggestedActions: [MeetingActionProposalDTO]?
    var summary: String?
    var decisions: [DecisionDTO]?
    var questionsAnswers: [QuestionAnswerDTO]?
    var sentimentAnalysis: SentimentAnalysisDTO?
    var customAnalysis: String?
    var transcriptDuration: Double
    var speakerCount: Int
    var processingTime: Double
    var meetingName: String?
    var meetingPurpose: String?
    var participants: [String]?
    var formattedDuration: String
    var formattedProcessingTime: String
    /// Full transcript for the analyzed meeting, when already available on
    /// the host (live analysis-complete or a selected history meeting), so
    /// the web UI can append a formatted `## Transcript` section to the
    /// copy-all/export text. `nil` on older callers that never populate it.
    var transcript: [TranscriptLineDTO]?
}

// MARK: - Window retranscription status

struct WindowRetranscriptionStatusDTO: Codable, Equatable, Identifiable {
    var id: String
    var source: String // "Microphone" | "SystemAudio"
    var start: Double
    var end: Double
    var phase: String // "running" | "applying" | "completed" | "failed"
    var message: String
}

// MARK: - Theme / fonts (reuses the AgentTask bridge's payload shapes)

typealias MeetingThemePayloadDTO = [String: String]
typealias MeetingFontPayloadDTO = [String: String]

// MARK: - Full UI scalar state

struct MeetingUIStateDTO: Codable, Equatable {
    var isRecording: Bool
    var statusMessage: String
    var recordingTimeString: String
    var connectionState: String // "ready" | "recording" | "error" | "connecting"
    var meetingName: String
    var meetingPurpose: String
    var meetingParticipants: String
    var isSystemAudioAvailable: Bool
    var availableAudioProcesses: [AudioProcessGroupDTO]
    var enableMicrophone: Bool
    var systemAudioCaptureMode: String // "none" | "selectedProcess" | "globalOutput"
    var selectedAudioProcessId: Int32?
    var transcriptionState: String // "loadingModels" | "idle" | "listening" | "transcribing"
    var accumulatedDuration: Double
    var lastTriggerReason: String?
    var availableModels: [TranscriptionModelInfoDTO]
    var selectedModel: String
    var isLoadingModels: Bool
    var hasRecordedAudio: Bool
    var hasTranscription: Bool
    var isPostProcessing: Bool
    var postProcessingModel: String
    var postProcessingProgress: Double
    var postProcessingStage: String
    var postProcessingMessage: String
    var postProcessingCurrentTime: Double
    var postProcessingTotalTime: Double
    var postProcessingETA: Double
    var postProcessingSourceIndex: Int
    var postProcessingSourceTotal: Int
    var postProcessingAggregateProgress: Double
    var postProcessingStartedAutomatically: Bool
    var activePostProcessingMeetingId: String?
    var sessionAutoRetranscribeOnStop: Bool
    var sessionAutoRetranscribeDuringRecording: Bool
    var sessionAutoAnalyzeOnComplete: Bool
    var sessionAutoAnalyzeModes: [String]
    var sessionAutoAnalyzeCustomInstructions: String
    var sessionAutoAnalyzeTiming: String
    var windowRetranscriptionStatus: WindowRetranscriptionStatusDTO?
    var isApplyingWindowedRetranscription: Bool
    var isAnalysisSectionExpanded: Bool
    var selectedAnalysisModes: [String]
    var analysisCustomInstructions: String
    var selectedAnalysisModelId: String?
    var localAnalysisModels: [ReasoningModelInfoDTO]
    var apiAnalysisModels: [ReasoningModelInfoDTO]
    var useApiModelsForAnalysis: Bool
    var isLoadingAnalysisModels: Bool
    var isAnalyzing: Bool
    var analysisProgress: Double
    var analysisMessage: String
    var currentAnalysisMode: String?
    var analysisJustCompleted: Bool
    var analysisStartedAutomatically: Bool
    var activeAnalysisMeetingId: String?
    var isLoadingAnalysisHistory: Bool
    var isLoadingAnalysisResult: Bool
    var analysisResultRequestedFilename: String?
    var analysisResultLoadError: String?
    var isSidebarCollapsed: Bool
    var isLoadingMeetings: Bool
    var isLoadingMoreMeetings: Bool
    var hasMoreMeetings: Bool
    var meetingHistoryLoadMoreError: String?
    var selectedMeetingId: String?
    var displayedMeetingWorkOwnerId: String?
    var isViewingPastMeeting: Bool
    var meetingSearchText: String
    var meetingSearchFilters: MeetingHistorySearchFiltersDTO
    var microphoneAudioLevel: Float
    var systemAudioLevel: Float
    var microphoneInputRecoveryState: String // "idle" | "reconnecting" | "failed"
    var microphoneInputRecoveryMessage: String?
    var isCapturePaused: Bool
    var isLiveTranscriptionEnabled: Bool
}

// MARK: - Outbound event envelope (Swift -> React)

/// One flattened, `type`-discriminated struct. Only the fields relevant to
/// `type` are non-nil for a given event; this mirrors the untyped-dictionary
/// convention already used by `AgentTaskResultWebView`, but keeps every field
/// name and type checked by the Swift compiler on the sending side.
struct MeetingBridgeEvent: Encodable {
    var type: String
    var revision: Int
    var selectionGeneration: Int
    var protocolVersion: Int = meetingBridgeProtocolVersion
    var ui: MeetingUIStateDTO?
    var transcript: [TranscriptLineDTO]?
    var transcriptPatch: TranscriptPatchDTO?
    var history: [MeetingListItemDTO]?
    var analysisHistory: [AnalysisMetadataEntryDTO]?
    var analysisResult: MeetingAnalysisResultDTO?
    var proposals: [MeetingActionProposalDTO]?
    var theme: MeetingThemePayloadDTO?
    var fonts: MeetingFontPayloadDTO?
    var validationErrorCode: String?
    var validationErrorMessage: String?

    enum CodingKeys: String, CodingKey {
        case type
        case revision
        case selectionGeneration
        case protocolVersion
        case ui
        case transcript
        case transcriptPatch
        case history
        case analysisHistory
        case analysisResult
        case proposals
        case theme
        case fonts
        case validationErrorCode
        case validationErrorMessage
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(type, forKey: .type)
        try container.encode(revision, forKey: .revision)
        try container.encode(selectionGeneration, forKey: .selectionGeneration)
        try container.encode(protocolVersion, forKey: .protocolVersion)
        try container.encodeIfPresent(ui, forKey: .ui)
        try container.encodeIfPresent(transcript, forKey: .transcript)
        try container.encodeIfPresent(transcriptPatch, forKey: .transcriptPatch)
        try container.encodeIfPresent(history, forKey: .history)
        try container.encodeIfPresent(analysisHistory, forKey: .analysisHistory)
        try container.encodeIfPresent(analysisResult, forKey: .analysisResult)
        try container.encodeIfPresent(proposals, forKey: .proposals)
        try container.encodeIfPresent(theme, forKey: .theme)
        try container.encodeIfPresent(fonts, forKey: .fonts)
        try container.encodeIfPresent(validationErrorCode, forKey: .validationErrorCode)
        try container.encodeIfPresent(validationErrorMessage, forKey: .validationErrorMessage)
    }
}

enum MeetingBridgeEventType {
    static let snapshot = "snapshot"
    static let sessionDelta = "sessionDelta"
    static let transcriptDelta = "transcriptDelta"
    static let historyDelta = "historyDelta"
    static let analysisHistoryDelta = "analysisHistoryDelta"
    static let analysisResultDelta = "analysisResultDelta"
    static let proposalsDelta = "proposalsDelta"
    static let themeChanged = "themeChanged"
    static let validationError = "validationError"
}

/// High-frequency audio meter values bypass the revisioned envelope entirely
/// (their own dedicated JS entry point) because they are a paint signal, not
/// a state transition; see `MeetingBridgePublisher.publishMeter`.
struct MeetingMeterPayload: Encodable {
    var microphoneAudioLevel: Float
    var systemAudioLevel: Float
}

// MARK: - Inbound intents (React -> Swift)

/// Every intent the React renderers may send. Swift decodes the raw
/// `[String: Any]` message body (see `MeetingAssistantWebView+IncomingBridge`)
/// against this closed list; anything unmatched is logged and dropped, never
/// executed. This enum has no associated-value payload of its own -- each
/// case documents which dictionary keys the handler reads.
enum MeetingBridgeIntent: String {
    case reactReady // { protocolVersion: Int }
    case closeWindow // {}
    case minimizeWindow // {}
    case toggleWindowCollapse // { collapsed: Bool }
    case chromeHeight // { height: Double }
    case toggleRecording // {}
    case startNewMeeting // {}
    case resumeMeeting // {}
    case pauseRecording // {}
    case resumeRecording // {}
    case cancelRecording // {}
    case setLiveTranscription // { enabled: Bool }
    case selectMeeting // { meetingId: String }
    case deleteMeeting // { meetingId: String }
    case setSidebarCollapsed // { collapsed: Bool }
    case setMeetingSearch // { text: String }
    case setMeetingSearchFilters // { queryMode, name, nameMode, purpose, purposeMode, participants, participantsMode, transcript, transcriptMode, source, sourceMode, startDate, endDate, processing, analysis }
    case loadMoreMeetings // {}
    case updateMetadata // { name: String?, purpose: String?, participants: String? }
    case setAudioSource // { enableMicrophone: Bool?, captureMode: String?, processId: Int32? }
    case setPostProcessingModel // { model: String }
    case startPostProcessing // {}
    case setAutomation // { autoRetranscribeOnStop: Bool?, autoRetranscribeDuringRecording: Bool?, autoAnalyzeOnComplete: Bool?, autoAnalyzeModes: [String]?, autoAnalyzeCustomInstructions: String?, autoAnalyzeTiming: String? }
    case setAnalysisConfiguration // { modes: [String]?, customInstructions: String?, modelId: String? }
    case startAnalysis // {}
    case viewAnalysis // { filename: String }
    case deleteAnalysis // { filename: String }
    case retryAnalysisModes // { filename: String, modes: [String] }
    case copyText // { text: String, rich: Bool }
    case exportAnalysis // { filename: String, format: String }
    case updateProposal // { proposalId: String, draftPrompt: String?, isEditingDraft: Bool? }
    case promoteProposalToTodo // { proposalId: String }
    case startProposalNow // { proposalId: String }
    case openProposalTodo // { todoId: String }
    case openProposalAgentTask // { agentTaskId: String }
    case promoteAllProposalsToTodos
    case dismissProposal // { proposalId: String }
    case restoreProposal // { proposalId: String }
}
