import SwiftUI
import Combine
import Foundation

@MainActor
final class AgentTaskCaptureViewModel: ObservableObject {
    // MARK: - Published Properties
    @Published var isCapturing: Bool = false
    @Published var remainingSeconds: Int = 10
    @Published var progressPercentage: CGFloat = 1.0
    @Published var audioLevel: Float = 0.0
    @Published var statusMessage: String = "Listening for request..."

    // MARK: - New Real-time Feedback Properties
    @Published var wordsDetected: [String] = []
    @Published var lastWordTime: Date?
    @Published var silenceDetectionActive: Bool = false
    @Published var silenceRemaining: Double = 0.0
    @Published var useIntelligentCapture: Bool = true

    // MARK: - Text Entry Mode Properties
    @Published var isTextEntryMode: Bool = false
    @Published var textPrompt: String = ""
    @Published var isSubmittingTextPrompt: Bool = false

    // MARK: - Model Selection Properties
    /// Optional per-capture reasoning-model override shared by voice and text submission paths.
    @Published var selectedAgentTaskModelId: String?

    // MARK: - Reference Materials Properties
    /// File or folder paths dropped onto the widget as context for the AgentTask.
    @Published var referencePaths: [URL] = []

    // Publisher for window size updates (when switching between audio/text modes)
    let sizeUpdateRequest = PassthroughSubject<(width: CGFloat, height: CGFloat), Never>()

    // MARK: - Private Properties
    var timerCancellable: AnyCancellable?
    var cancellables = Set<AnyCancellable>()
    let totalDuration: Int = 10
    var startTime: Date?
    var hasCompleted: Bool = false // Flag to prevent multiple completion calls

    // WebSocket service for real-time events
    let webSocketService: WebSocketService

    // Completion handlers
    var onCaptureComplete: (() -> Void)?
    var onCaptureCanceled: (() -> Void)?

    // Audio capture service for real audio levels
    let audioCaptureService = AudioCaptureService()

    // Explicit task-thread IDs for follow-up turns.
    let rootTaskId: String?
    let previousTaskId: String?

    // Pre-generated AgentTask ID (for new AgentTasks started from result widget)
    // When set, this ID will be passed to the backend instead of letting backend generate one
    var preGeneratedAgentTaskId: String?

    /// Default input modality applied on the very first `startCapture()` call.
    /// When `.text`, audio capture is skipped entirely and the widget opens directly
    /// in text-entry mode. Consumed (reset to `.voice`) on first use, so subsequent
    /// re-arms via `enterVoiceMode()` go down the normal audio path.
    var pendingInitialModality: AgentTaskInputModality = .voice

    // MARK: - Initialization
    init(webSocketService: WebSocketService? = nil, rootTaskId: String? = nil, previousTaskId: String? = nil) {
        self.webSocketService = webSocketService ?? WebSocketService.shared
        self.rootTaskId = rootTaskId
        self.previousTaskId = previousTaskId

        #if DEBUG
        DevLogger.shared.info("AgentTaskCaptureViewModel initialized", context: "AgentTaskCapture")
        #endif

        // Observe real audio levels from the capture service
        audioCaptureService.$audioLevel
            .receive(on: DispatchQueue.main)
            .sink { [weak self] level in
                self?.audioLevel = level
            }
            .store(in: &cancellables)

        // Set up WebSocket event subscription for real-time feedback
        setupWebSocketSubscription()
    }

    // MARK: - Cleanup
    deinit {
        // Clean up any remaining resources
        timerCancellable?.cancel()
        cancellables.removeAll()

        #if DEBUG
        DevLogger.shared.info("AgentTaskCaptureViewModel deinitialized", context: "AgentTaskCapture")
        #endif
    }
}
