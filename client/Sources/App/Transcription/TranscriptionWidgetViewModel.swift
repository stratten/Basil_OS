import SwiftUI
import Combine

enum TranscriptionRecordingLifecycle: Equatable {
    case idle
    case starting
    case recording
    case processing
    case failed

    var isRecording: Bool { self == .recording }
    var isProcessing: Bool { self == .processing }
    var isStarting: Bool { self == .starting }
}

@MainActor
protocol TranscriptionAudioCaptureControlling: AnyObject {
    var hasCapturedAudioData: Bool { get }
    func prepareRecordingPipelineIfAuthorized() async
    func setContextInfo(appName: String?, windowTitle: String?, taskCategory: String?)
    func startRecording(flowContext: String?) async throws
    func cancelRecordingStartup()
    func stopRecording(sendAudioData: Bool, flowContext: String?, context: [String: Any]?)
}

extension AudioCaptureService: TranscriptionAudioCaptureControlling {
    var hasCapturedAudioData: Bool {
        lastRecordingData != nil
    }
}

@MainActor
final class TranscriptionWidgetViewModel: ObservableObject {
    @Published var transcriptionText: String {
        willSet {
            #if DEBUG
            DevLogger.shared.info("Transcription text changing from: \"\(transcriptionText)\" to: \"\(newValue)\"", context: "text_state")
            #endif
        }
    }
    @Published private(set) var recordingLifecycle: TranscriptionRecordingLifecycle = .idle {
        didSet {
            let previousRecording = isRecording
            isRecording = recordingLifecycle.isRecording
            isProcessingRecording = recordingLifecycle.isProcessing
            if previousRecording != isRecording {
                NotificationCenter.default.post(
                    name: NSNotification.Name("RecordingStateChanged"),
                    object: nil,
                    userInfo: [
                        "isRecording": isRecording,
                        "previousState": previousRecording,
                        "source": "transcription"
                    ]
                )
            }
        }
    }
    @Published private(set) var isRecording: Bool = false {
        willSet {
            #if DEBUG
            DevLogger.shared.info("Recording state changing from: \(isRecording) to: \(newValue)", context: "TranscriptionWidget")
            #endif
        }
        didSet {
            #if DEBUG
            DevLogger.shared.info("Recording state changed to: \(isRecording)", context: "TranscriptionWidget")
            #endif
            if isRecording {
                startRecordingTimer()
            } else {
                stopRecordingTimer()
            }
        }
    }
    @Published var isConnected: Bool = false
    @Published var error: String?
    @Published var pulseScale: CGFloat = 1.0
    private let audioLevelSubject = CurrentValueSubject<Float, Never>(0.0)
    var audioLevel: Float { audioLevelSubject.value }
    var audioLevelPublisher: AnyPublisher<Float, Never> { audioLevelSubject.eraseToAnyPublisher() }

    func updateAudioLevel(_ level: Float) {
        audioLevelSubject.send(max(0, min(level, 1)))
    }

    @Published var isModelReady: Bool = false
    @Published var isModelLoading: Bool = false
    @Published private(set) var isProcessingRecording: Bool = false
    @Published var elapsedSeconds: Int = 0
    @Published var isMinimized: Bool = false {
        didSet {
            #if DEBUG
            DevLogger.shared.info("Widget minimized state changed to: \(isMinimized)", context: "TranscriptionWidget")
            #endif
            saveMinimizedState()
        }
    }
    @Published var preventRecordingStop: Bool = false

    // MARK: - In-widget transcription model picker state
    //
    // Drives the new `TranscriptionModelPickerMenu` rendered inside the
    // mini and full widget layouts. The widget is the only path that
    // can produce a *live* model swap -- the existing Settings tab only
    // persists preferences without unloading/reloading. See
    // `swapTranscriptionModel(to:)` below for the behavior.
    @Published var availableTranscriptionModels: [TranscriptionModelOption] = []
    @Published var currentTranscriptionModelId: String = ""
    @Published var isSwappingTranscriptionModel: Bool = false

    let audioCaptureService: AudioCaptureService
    let webSocketService: WebSocketService
    var cancellables = Set<AnyCancellable>()
    var timerCancellable: AnyCancellable?
    let audioCaptureController: any TranscriptionAudioCaptureControlling
    var recordingStartupTask: Task<Void, Never>?
    var recordingStartupWatchdogTask: Task<Void, Never>?
    var activeRecordingStartupID: UUID?
    var pendingAutoStartRecording = false
    static let recordingStartupTimeoutNanoseconds: UInt64 = 5_000_000_000

    var isStartingRecording: Bool {
        recordingLifecycle.isStarting || pendingAutoStartRecording
    }

    var canToggleRecording: Bool {
        isConnected && recordingLifecycle != .processing
    }

    init(
        webSocketService: WebSocketService? = nil,
        audioCaptureController: (any TranscriptionAudioCaptureControlling)? = nil
    ) {
        if let service = webSocketService {
            self.webSocketService = service
        } else {
            self.webSocketService = WebSocketService.shared
        }
        let captureService = AudioCaptureService()
        self.audioCaptureService = captureService
        self.audioCaptureController = audioCaptureController ?? captureService
        captureService.setWebSocketService(self.webSocketService)
        self.transcriptionText = "Initializing transcription service..."
    }

    func transitionRecordingLifecycle(to lifecycle: TranscriptionRecordingLifecycle) {
        recordingLifecycle = lifecycle
    }
}
