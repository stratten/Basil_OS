import SwiftUI
import Combine
import Foundation

// MARK: - Main ViewModel Declaration
// Core AssistantSession functionality split across extensions:
// - AssistantSessionViewModel+Core.swift: Initialization and lifecycle
// - AssistantSessionViewModel+MainFlow.swift: Primary OCR → Recording → Upload workflow
// - AssistantSessionViewModel+Refinement.swift: Iterative refinement mode
// - AssistantSessionViewModel+Editing.swift: Edit mode and sample saving
// - AssistantSessionViewModel+Utilities.swift: Helper functions (thinking, pasting, throttling)
// - AssistantSessionViewModel+UI.swift: UI sizing and layout management

@MainActor
final class AssistantSessionViewModel: ObservableObject {
    // MARK: - Publishers
    let idealSizeUpdateRequest = PassthroughSubject<(width: CGFloat, height: CGFloat), Never>()

    // MARK: - Progress States
    @Published var ocrStatus: Status = .idle
    @Published var transcriptionStatus: Status = .idle
    @Published var assistantSessionStatus: Status = .idle
    @Published var errorMessage: String?
    @Published var combinedResult: String = ""
    @Published var assistantOutput: String = ""
    @Published var thinkingContent: String? = nil
    @Published var isRecording: Bool = false
    @Published var audioLevel: Float = 0.0
    @Published var elapsedSeconds: Int = 0
    @Published var transcriptionText: String = ""
    @Published var transcriptionProgressMessage: String?
    @Published var transcriptionProgressFraction: Double?
    @Published var shouldPersistUI: Bool = false
    
    // MARK: - Throttling Properties
    var lastAssistantSessionUpdateTime: Date = Date.distantPast
    let assistantSessionUpdateThrottleInterval: TimeInterval = 0.2
    var pendingAssistantSessionUpdate: String?
    var assistantSessionUpdateTask: Task<Void, Never>?
    
    var lastSizeUpdateTime: Date = Date.distantPast
    let sizeUpdateThrottleInterval: TimeInterval = 0.3
    var pendingSizeUpdate: Bool = false
    var sizeUpdateTask: Task<Void, Never>?

    // MARK: - UI Properties
    @Published var currentIdealTextHeight: CGFloat = 120
    @Published var isResultChromeCollapsed: Bool = false

    // MARK: - Text Selection Properties
    @Published var hasTextSelection: Bool = false
    @Published var selectionContext: TextSelectionResult?
    let textSelectionService: TextSelectionService

    // MARK: - Detected Application
    /// Frontmost application name as reported by `WindowCaptureService`'s
    /// AppleScript at the moment the AssistantSession hotkey fired. The legacy
    /// Enhanced Suggestion widget read `viewModel.appName` (seeded from
    /// `CaptureResult.appName`) for its "Detected Application:" strip; this
    /// is the same value, restored on the unified AssistantSession widget.
    ///
    /// Kept separate from `selectionContext.applicationName` because the two
    /// have different jobs: this is the canonical AppleScript-derived
    /// frontmost-process name (always available when capture succeeds);
    /// `selectionContext` carries the *selected text* and only resolves an
    /// app name as a side effect of the accessibility-based detection
    /// strategies, which return `TextSelectionResult.empty` (and therefore
    /// `applicationName = "Unknown"`) any time no text is highlighted -- the
    /// common case for the typed-input modality.
    @Published var detectedApplicationName: String?

    // MARK: - Refinement Mode Properties
    @Published var isRefinementMode: Bool = false
    @Published var iterationCount: Int = 0
    @Published var showRefinementIndicator: Bool = false
    @Published var refinementPrompt: String = "Refine your request..."
    /// Incremented when native code asks the web surface to open the typed refinement editor (e.g. the history item's typed Refine). The web surface opens the editor once per new value.
    @Published var typedRefinementRequestSerial: Int = 0
    var initialRequest: String = ""
    var currentRequest: String = ""

    // MARK: - Input Modality Properties
    /// Which entry modality the widget is currently presenting. Defaults to
    /// `.speak` (legacy behavior); the hotkey handler overrides this from
    /// `assistantSession.default_input_modality` before invoking the flow,
    /// and the widget header toggle flips it at runtime. The `MainFlow`
    /// orchestrator branches on this after OCR/session start: `.speak`
    /// keeps the existing record-then-upload path; `.type` skips recording
    /// and waits for the user to submit `typedInstruction`.
    @Published var inputMode: AssistantSessionInputMode = .speak
    /// Buffer for the typed-input modality. Drained on submit. An empty
    /// trimmed value at submit time is the explicit "no instruction"
    /// signal -- the unified pipeline route accepts a multipart request
    /// with neither `audio_file` nor `instruction_text` and the server
    /// substitutes the no-input default prompt.
    @Published var typedInstruction: String = ""
    /// Latch that the typed-input view sets to request submission via the
    /// MainFlow continuation. Avoids the view directly invoking network
    /// helpers and keeps the orchestration single-threaded inside the
    /// view model. Today this is set in lockstep with `inputCommitted` --
    /// kept as a separate signal for telemetry / future divergence.
    @Published var typedInputSubmissionRequested: Bool = false
    /// Single source of truth for "the user has committed their input
    /// and the widget should now stop accepting modality changes."
    /// Mirrors the agentTask capture widget's implicit lock-on-commit
    /// (where the widget is dismissed after `onCaptureComplete?()`).
    /// AssistantSession's widget stays visible through processing/result, so we
    /// need an explicit gate. Set true by `stopRecording()` (speak
    /// commit) and `submitTypedInstruction()` (type commit). Reset to
    /// false at the top of `startAssistantSessionFlow`. Drives both the
    /// header toggle's visibility and the post-OCR
    /// `awaitInputCommit()` continuation.
    @Published var inputCommitted: Bool = false

    // MARK: - Model Selection Properties (typed-input modality)
    /// Reasoning model picker state for the typed-input slot. Mirrors
    /// the field set on the legacy `EnhancedSuggestionInputViewModel` so
    /// the model-loading and selection logic recovered in
    /// `AssistantSessionViewModel+Models.swift` is a one-to-one port.
    /// Speak-modality model selection is intentionally NOT surfaced here
    /// yet -- it will land later as a hover-revealed minimal control on
    /// the recording UI per the agreed plan, not as a duplicate picker.
    /// `selectedModelId` is forwarded to the unified
    /// `/assistant-sessions/{id}/process-input` route via the
    /// `model_id` form field (the route already accepts it).
    @Published var selectedModelId: String?
    @Published var availableModels: [ModelServiceInfo] = []
    @Published var localModels: [ModelServiceInfo] = []
    @Published var apiModels: [ModelServiceInfo] = []
    @Published var useApiModels: Bool = false
    @Published var isLoadingModels: Bool = false

    // MARK: - Save as Sample Properties
    @Published var sampleSaved: Bool = false
    @Published var savingSample: Bool = false

    // MARK: - Edit Mode Properties
    @Published var isEditMode: Bool = false {
        didSet {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] isEditMode changed to: \(isEditMode)", context: "AssistantSessionViewModel")
            #endif
        }
    }
    @Published var editableContent: String = "" {
        didSet {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] editableContent changed: length=\(editableContent.count), isEmpty=\(editableContent.isEmpty)", context: "AssistantSessionViewModel")
            #endif
        }
    }

    // MARK: - Internal Storage
    var ocrText: String?
    var cancellables = Set<AnyCancellable>()
    var currentIdealWidgetWidth: CGFloat = 400
    var currentIdealWidgetHeight: CGFloat = 400
    var expandedResultWidgetWidth: CGFloat = 520
    var expandedResultWidgetHeight: CGFloat = 250

    // MARK: - Services
    let audioCaptureService: AudioCaptureService
    
    // MARK: - Callbacks
    var onMinimize: (() -> Void)?

    // MARK: - Session Management
    var sessionId: String? = nil

    var timerCancellable: AnyCancellable?
    var recordingStartDate: Date?
    
    // MARK: - Task Management
    var ocrStreamingTask: Task<Void, Never>? = nil
    var audioUploadTask: Task<Void, Never>? = nil
    var recordingMonitorTask: Task<Void, Never>? = nil
    var isCanceled: Bool = false

    // MARK: - Status Enum
    enum Status: String {
        case idle, running, completed, failed
    }

    // MARK: - Nested Types
    struct AssistantSessionStartChunk: Decodable {
        let session_id: String
        let ocr_text: String?
        let error: String?
    }

    struct AssistantSessionStartRequest: Codable {
        let image_path: String
    }
    
    // MARK: - Streaming State
    struct StreamingState {
        var content: String = ""
        var thinking: String = ""
        var buffer: String = ""
        var isInsideThinking: Bool = false
    }
    var streamingState: StreamingState? = nil
    
    // MARK: - Initialization
    
    init(webSocketService: WebSocketService? = nil, textSelectionService: TextSelectionService? = nil) {
        self.audioCaptureService = AudioCaptureService()
        self.textSelectionService = textSelectionService ?? TextSelectionService()
        
        // Initialize async setup that includes recording state notifications
        Task { @MainActor in
            await self.initialize()
        }
    }
    
    // MARK: - Deinitialization
    
    deinit {
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] ViewModel deinit called (deallocated): \(ObjectIdentifier(self))", context: "AssistantSessionViewModel")
        #endif
        
        // Cancel any ongoing tasks during deallocation
        ocrStreamingTask?.cancel()
        audioUploadTask?.cancel()
        recordingMonitorTask?.cancel()
        timerCancellable?.cancel()
    }
}
