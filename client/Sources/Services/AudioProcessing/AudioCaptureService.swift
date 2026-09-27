import Foundation
import AVFoundation
import Combine

@MainActor
final class AudioCaptureService: NSObject, ObservableObject {
    static var activeRecordingOwnersByInstance: [String: String] = [:]

    let recordingRegistryId = UUID().uuidString

    // MARK: - Published Properties
    @Published var isRecording: Bool = false {
        willSet {
            #if DEBUG
                DevLogger.shared.info("AudioCaptureService: isRecording changing from \(isRecording) to \(newValue)", context: "AudioCapture")
            #endif
        }
        didSet {
            #if DEBUG
                DevLogger.shared.info("AudioCaptureService: isRecording changed to \(isRecording)", context: "AudioCapture")
            #endif
        }
    }
    @Published var error: String?
    @Published var permissionGranted = false
    @Published var audioLevel: Float = 0.0
    @Published var elapsedSeconds: Int = 0
    
    // MARK: - Properties
    // Use an optional AVAudioEngine to recreate per session and release hardware
    var audioEngine: AVAudioEngine? = nil
    var recordingData = Data()
    var activeRecordingStartID: UUID?
    let audioEngineOperationQueue = AudioEngineOperationQueue()
    var firstBufferStartID: UUID?
    var firstBufferContinuation: CheckedContinuation<Void, Error>?
    var isAudioTapPrepared = false
    var recordingPipelinePreparationTask: Task<Void, Error>?
    var recordingPipelineGeneration = 0
    var validationSyntheticAudioSource: ValidationSyntheticAudioCaptureSource?
    var webSocketService: WebSocketService?
    
    // Audio tap retry management - prevents infinite retry loops
    var silentRetryCount = 0
    var audioTapDiagnosticBufferCount = 0
    
    // Context information
    var contextInfo: [String: String?] = [
        "app_name": nil,
        "window_title": nil,
        "task_category": nil
    ]
    
    // Audio format - 16kHz mono float32
    lazy var audioFormat: AVAudioFormat? = {
        return AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 16000,
            channels: 1,
            interleaved: false
        )
    }()
    
    // Input format for capturing
    var inputFormat: AVAudioFormat? {
        return audioEngine?.inputNode.inputFormat(forBus: 0)
    }
    
    // Audio level calculation
    let audioLevelUpdateInterval: TimeInterval = 0.1
    var lastAudioLevelUpdate: TimeInterval = 0
    
    // Add a property to store the current flow context
    var currentFlowContext: String? = nil

    // Static registry for all engine instances (for diagnostics)
    var allEnginePointers = Set<String>()
    
    // MARK: - Initialization
    convenience init(webSocketService: WebSocketService? = nil) {
        self.init(
            webSocketService: webSocketService,
            validationSyntheticAudioSource:
                ValidationSyntheticAudioCaptureSource.configuredForCurrentRuntime()
        )
    }

    init(
        webSocketService: WebSocketService?,
        validationSyntheticAudioSource: ValidationSyntheticAudioCaptureSource?
    ) {
        self.webSocketService = webSocketService
        self.validationSyntheticAudioSource = validationSyntheticAudioSource
        super.init()
        
        // Setup audio session
        setupAudioSession()
        
        if validationSyntheticAudioSource == nil {
            // Initialize the real microphone engine only outside synthetic validation.
            setupAudioEngine()
        } else {
            permissionGranted = true
            #if DEBUG
            DevLogger.shared.info(
                "Using the isolated validation synthetic transcription source",
                context: "AudioCaptureService"
            )
            #endif
        }

        guard validationSyntheticAudioSource == nil else {
            return
        }
        
        // Only check current permission state, don't request
        let authStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        #if DEBUG
            DevLogger.shared.info("Initializing AudioCaptureService - Current permission state: \(authStatus.rawValue)", context: "permissions")
        #endif
        
        // Update our state based on current permissions
        switch authStatus {
        case .authorized:
            permissionGranted = true
            #if DEBUG
                DevLogger.shared.info("✅ Audio permissions are authorized", context: "permissions")
            #endif
        case .denied:
            permissionGranted = false
            error = "Microphone access required. Click here to open System Settings."
            #if DEBUG
                DevLogger.shared.warning("❌ Audio permissions explicitly denied", context: "permissions")
            #endif
        case .restricted:
            permissionGranted = false
            error = "Microphone access is restricted by system settings."
            #if DEBUG
                DevLogger.shared.warning("⚠️ Audio permissions restricted by system", context: "permissions")
            #endif
        case .notDetermined:
            // Don't request here - AppDelegate will handle the initial request
            permissionGranted = false
            #if DEBUG
                DevLogger.shared.info("ℹ️ Audio permissions not yet determined - waiting for AppDelegate to handle", context: "permissions")
            #endif
        @unknown default:
            permissionGranted = false
            #if DEBUG
                DevLogger.shared.warning("❓ Unknown audio permission state: \(authStatus.rawValue)", context: "permissions")
            #endif
        }
    }
    
    func setWebSocketService(_ service: WebSocketService) {
        self.webSocketService = service
    }
    
    deinit {
        recordingPipelinePreparationTask?.cancel()
        firstBufferContinuation?.resume(throwing: CancellationError())
        firstBufferContinuation = nil
        firstBufferStartID = nil
        if let engine = audioEngine {
            NotificationCenter.default.removeObserver(
                self,
                name: .AVAudioEngineConfigurationChange,
                object: engine
            )
        }
    }
}
