import Foundation
import AVFoundation
import Combine
import SwiftUI

@MainActor
class LiveTranscriptionViewModel: ObservableObject {
    // MARK: - Published Properties
    @Published var isRecording = false
    @Published var statusMessage = "Ready to start transcription"
    @Published var transcriptionLines: [TranscriptionLine] = []  // Combined view (interleaved by timestamp)
    @Published var microphoneTranscript: [TranscriptionLine] = []  // Microphone-only transcript
    @Published var systemAudioTranscript: [TranscriptionLine] = []  // System audio-only transcript
    @Published var recordingTimeString = "00:00"
    private let microphoneAudioLevelSubject = CurrentValueSubject<Float, Never>(0.0)
    private let systemAudioLevelSubject = CurrentValueSubject<Float, Never>(0.0)
    var microphoneAudioLevel: Float { microphoneAudioLevelSubject.value }
    var systemAudioLevel: Float { systemAudioLevelSubject.value }
    var microphoneAudioLevelPublisher: AnyPublisher<Float, Never> { microphoneAudioLevelSubject.eraseToAnyPublisher() }
    var systemAudioLevelPublisher: AnyPublisher<Float, Never> { systemAudioLevelSubject.eraseToAnyPublisher() }
    @Published var connectionState: ConnectionState = .ready
    @Published var meetingName: String  // Auto-generated timestamp, but editable
    @Published var meetingPurpose = ""
    @Published var meetingParticipants = ""
    @Published var isSystemAudioAvailable: Bool = false
    @Published private(set) var availableAudioProcesses: [AudioProcessGroup] = []
    
    // Audio source toggles
    @Published var enableMicrophone: Bool = true  // Toggle to enable/disable microphone recording
    @Published var systemAudioCaptureMode: SystemAudioCaptureMode = .globalOutput

    // Capture controls for the active recording part (see LiveTranscriptionViewModel+CaptureControl).
    @Published var isCapturePaused = false
    @Published var sessionLiveTranscriptionEnabled = true
    var liveTranscriptionSelectionTouched = false
    var liveTranscriptionWasDisabledThisPart = false
    let recordingClock = RecordingClock()
    
    // Event-driven batched transcription state
    @Published var transcriptionState: TranscriptionState = .loadingModels
    @Published var accumulatedDuration: Double = 0.0
    @Published var lastTriggerReason: String?
    
    // Model selection
    @Published var availableModels: [String] = []
    @Published var transcriptionModelOptions: [TranscriptionModelOption] = []
    @Published var selectedModel: String = ""
    @Published var isLoadingModels: Bool = false
    
    // Meeting management - dual sources
    @Published var microphoneMeetingId: String?
    @Published var systemAudioMeetingId: String?
    // Shared id that links the mic + system-audio recordings of a single meeting
    // so the backend can group them and reopen them as one interleaved transcript.
    var sessionId: String?
    // Bundle ID this recording was auto-started for (meeting detection). Used to
    // match a backend `meeting_ended` event so auto-end only finalizes the
    // recording that the detection actually started.
    var autoStartedBundleID: String?
    
    // MARK: - Recording-part / resume context
    // Drives whether the next recording starts a fresh meeting or resumes an
    // existing logical meeting. Managed in LiveTranscriptionViewModel+RecordingSession.
    enum RecordingMode {
        case fresh
        case resume
    }
    var recordingMode: RecordingMode = .fresh
    // Offset (seconds) where a resumed part begins on the logical meeting timeline.
    var resumeTimelineOffsetSeconds: Double = 0.0
    // Stable ordering index of the current recording part among resumed parts.
    var recordingPartIndex: Int = 0
    // The meeting id this recording was resumed from (diagnostics / grouping).
    var resumedFromMeetingId: String?
    @Published var hasRecordedAudio: Bool = false
    @Published var hasTranscription: Bool = false  // True after transcription completes (allows diarization)
    let backgroundWorkCoordinator = MeetingBackgroundWorkCoordinator()
    
    // Backward compatibility: returns mic meeting ID if available, otherwise system audio
    var currentMeetingId: String? {
        return microphoneMeetingId ?? systemAudioMeetingId
    }
    
    // Post-processing state
    @Published var isPostProcessing: Bool = false
    @Published var postProcessingModel: String = ""
    @Published var postProcessingProgress: Double = 0.0
    @Published var postProcessingStage: String = ""
    @Published var postProcessingMessage: String = ""
    @Published var postProcessingCurrentTime: Double = 0.0
    @Published var postProcessingTotalTime: Double = 0.0
    @Published var postProcessingETA: Double = 0.0
    // Which audio source (1-based) of how many total is currently being
    // re-transcribed. Retranscription runs one backend job per source file, but
    // the duration readout is the cross-source aggregate; these let the UI show
    // "source i of n" instead of mixing a per-file count with an aggregate clock.
    @Published var postProcessingSourceIndex: Int = 0
    @Published var postProcessingSourceTotal: Int = 0
    // The meeting whose retranscription is actually in flight. The progress
    // overlay is only shown when this matches the currently-selected meeting so
    // the bar does not appear on unrelated meetings the user opens mid-process.
    @Published var activePostProcessingMeetingId: String? = nil
    // Combined-duration progress across both sequential tracks (mic + system).
    // Distinct from per-track postProcessingProgress so the bar advances
    // monotonically 0->100% across the whole workload rather than resetting
    // between tracks.
    @Published var postProcessingAggregateProgress: Double = 0.0
    @Published var postProcessingStartedAutomatically: Bool = false
    // Per-source start offsets (seconds) onto the shared session origin, used to
    // correct cross-track start skew when post-processed segments are swapped in.
    // Populated from member start times when known; empty (0 offset) otherwise.
    var postProcessingSourceStartOffsets: [AudioSource: Double] = [:]

    // Per-session post-processing automation overrides. Seeded from the global
    // transcription settings when a recording starts; editable in the Transcript
    // Tools card to change a single run without mutating the saved defaults.
    @Published var sessionAutoRetranscribeOnStop: Bool = false
    @Published var sessionAutoAnalyzeOnComplete: Bool = false
    @Published var sessionAutoAnalyzeModes: [String] = []
    @Published var sessionAutoAnalyzeCustomInstructions: String = ""
    @Published var sessionAutoAnalyzeTiming: String = "after"
    // Mid-recording incremental re-transcription (threshold cadence). When
    // enabled, elapsed windows are re-transcribed with the higher-quality
    // post-processing model while recording continues and spliced into the live
    // transcript. The interval is the cadence (seconds) between window upgrades.
    @Published var sessionAutoRetranscribeDuringRecording: Bool = false
    var sessionRetranscribeWindowSeconds: Int = 600
    // Last upgraded checkpoint (absolute meeting seconds) per track meeting id,
    // so each window covers only newly-elapsed audio and the on-stop tail knows
    // where cadence left off.
    var lastRetranscribeCheckpointByMeeting: [String: Double] = [:]
    // Cadence loop + a single-in-flight guard so a slow large-model window never
    // overlaps the next tick (bounds load against the live ASR).
    var retranscribeCadenceTask: Task<Void, Never>?
    var retranscribeWindowInFlight: Bool = false
    @Published var windowRetranscriptionStatus: WindowRetranscriptionStatus?
    @Published var isApplyingWindowedRetranscription: Bool = false
    // True once the session overrides have been seeded from global defaults for
    // the current recording, so re-fetching settings does not clobber edits.
    var sessionAutomationSeeded: Bool = false
    
    // Analysis state
    @Published var isAnalysisSectionExpanded: Bool = false
    @Published var selectedAnalysisModes: Set<AnalysisMode> = []
    @Published var analysisCustomInstructions: String = ""
    @Published var selectedAnalysisModelId: String? = nil
    @Published var localAnalysisModels: [ReasoningModelInfoVM] = []
    @Published var apiAnalysisModels: [ReasoningModelInfoVM] = []
    @Published var useApiModelsForAnalysis: Bool = false
    @Published var isLoadingAnalysisModels: Bool = false
    @Published var isAnalyzing: Bool = false
    @Published var analysisProgress: Double = 0.0
    @Published var analysisMessage: String = ""
    @Published var currentAnalysisMode: String? = nil
    // Set true when an analysis finishes successfully so the UI can show a
    // persistent "Analysis complete" indicator without the user navigating
    // away and back. Cleared when a new analysis starts or the selection changes.
    @Published var analysisJustCompleted: Bool = false
    @Published var analysisStartedAutomatically: Bool = false
    // The meeting whose analysis is actually in flight (or just completed). The
    // progress overlay and completion badge are only shown when this matches the
    // currently-selected meeting, so an analysis started on meeting A does not
    // render its bar/badge on a different meeting B the user opens mid-process
    // (mirrors activePostProcessingMeetingId for retranscription).
    @Published var activeAnalysisMeetingId: String? = nil
    /// Set once by `MeetingSessionCoordinator.ensureSession()` immediately
    /// after constructing this view model. Never constructed by, or nilled
    /// from, this class itself -- `showAnalysisResults` only reads it to
    /// delegate to `MeetingSessionCoordinator.showAnalysisResult(_:)`.
    weak var meetingSessionCoordinator: MeetingSessionCoordinator?
    @Published var analysisHistory: [AnalysisMetadataEntry] = []
    @Published var isLoadingAnalysisHistory: Bool = false
    @Published var isLoadingAnalysisResult: Bool = false
    @Published var analysisResultRequestedFilename: String?
    @Published var analysisResultLoadError: String?
    
    // Meeting history state
    @Published var isSidebarCollapsed: Bool = false
    @Published var meetings: [MeetingListItem] = []
    @Published var selectedMeetingId: String?  // ID of currently viewed past meeting (nil = new/current)
    @Published var isLoadingMeetings: Bool = false
    @Published var isLoadingMoreMeetings: Bool = false
    @Published var hasMoreMeetings: Bool = false
    @Published var meetingHistoryLoadMoreError: String?
    @Published var loadedMeetingTranscript: BackendMeetingTranscript?  // Transcript of loaded past meeting
    @Published var isViewingPastMeeting: Bool = false  // True when viewing a past meeting (read-only mode)
    // Sidebar full-text search over meeting transcripts/metadata. Empty == the
    // normal recent-meetings list; non-empty routes loadMeetingHistory() through
    // the backend /meetings/search endpoint (debounced via meetingSearchTask).
    @Published var meetingSearchText: String = ""
    @Published var meetingSearchFilters = MeetingHistorySearchFilters()
    var meetingSearchTask: Task<Void, Never>?
    var meetingHistoryRequestGeneration = 0
    
    // Sidebar state persistence
    @AppStorage("liveTranscription.sidebarCollapsed") var storedSidebarCollapsed: Bool = false
    
    // MARK: - Internal Properties (accessible to extensions)
    var audioEngine: AVAudioEngine?
    // Measures the true microphone input sample rate from tap callback throughput
    // so resampling to 16kHz uses the real rate, not the (possibly stale/wrong)
    // declared input format - see AudioInputRateEstimator for the AirPods/aggregate
    // -device motivation. Reset once per setupAudioEngine() call (i.e. once per
    // recording part, including resumed parts); only ever touched inside the tap
    // callback, which runs on CoreAudio's serial IO thread.
    let microphoneRateEstimator = AudioInputRateEstimator()
    var microphoneWebSocketTask: URLSessionWebSocketTask?  // Dedicated WebSocket for microphone audio
    var systemAudioWebSocketTask: URLSessionWebSocketTask?  // Dedicated WebSocket for system audio
    // Per-source reconnect debounce. A dead socket fails ~10 sends/sec; without
    // these flags every failed chunk would spawn its own reconnect (a storm).
    // Set true while a single reconnect for that source is in flight.
    var microphoneReconnectInFlight = false
    var systemAudioReconnectInFlight = false
    // Reset after a successful source connection or when recording stops.
    // Incremented for each retry to apply capped exponential backoff.
    var microphoneReconnectAttempt = 0
    var systemAudioReconnectAttempt = 0
    var microphoneEngineConfigurationObserver: NSObjectProtocol?
    var microphoneInputRecoveryTask: Task<Void, Never>?
    var microphoneWebSocketRecoveryTask: Task<Void, Never>?
    var microphoneRecoveryGeneration = 0
    @Published var microphoneInputRecoveryState: MicrophoneInputRecoveryState = .idle
    // Tracks the system-audio socket's initial-readiness wait, mirroring
    // `connectionTask`/`connectionError` above but kept separate: mic and
    // system-audio connections are established concurrently in
    // startRecording(), so they cannot share one pair of tracking properties.
    var systemAudioConnectionTask: Task<Void, Error>?
    var systemAudioConnectionError: Error?
    var analysisWebSocketTask: URLSessionWebSocketTask?  // WebSocket for analysis progress
    var postProcessingWebSocket: URLSessionWebSocketTask?
    var meetingMetadataSaveTask: Task<Void, Never>?
    var recordingStartTime: Date?

    // A newly created source socket must receive its capture-time control
    // message before it can send PCM, including after reconnecting.
    var microphoneStreamTimingReady = false
    var systemAudioStreamTimingReady = false
    
    // Backward compatibility: returns mic WebSocket if available, otherwise system audio
    var webSocketTask: URLSessionWebSocketTask? {
        return microphoneWebSocketTask ?? systemAudioWebSocketTask
    }
    var timerCancellable: AnyCancellable?
    var transcriptionSettings: TranscriptionSettings?
    var websocketUrl: String {
        let port = APIClient.shared.currentPort
        return "ws://localhost:\(port)/whisper-live/asr"
    }
    var cancellables = Set<AnyCancellable>()
    var _systemAudioState: Any?
    var processObserver: AnyCancellable?
    var connectionTask: Task<Void, Error>?
    var connectionError: Error?
    var messageLogCounter: Int = 0  // Counter for reducing log noise
    
    // Single global timer for line break detection (3 second silence from ALL sources = new line)
    var globalLineBreakTimer: Task<Void, Never>?
    var lastBufferSendTime: TimeInterval?
    var isCleaningUp: Bool = false  // Prevent timer recreation during cleanup
    
    // MARK: - Public Properties

    func updateMicrophoneAudioLevel(_ level: Float) {
        microphoneAudioLevelSubject.send(max(0, min(level, 1)))
    }

    func updateSystemAudioLevel(_ level: Float) {
        systemAudioLevelSubject.send(max(0, min(level, 1)))
    }
    
    // MARK: - Internal Types (accessible to extensions)
    
    /// Settings for transcription from backend
    struct TranscriptionSettings: Codable {
        let model_unload_delay: Int
        let auto_paste: Bool
        let auto_close_on_paste: Bool
        let language: String
        let selected_model: String
        let widget_size: WidgetSize?
        let widget_position: WidgetPosition?
        // Meeting post-processing automation defaults (see backend
        // TranscriptionSettings). Defaulted + defensively decoded so older
        // payloads decode without error.
        var auto_retranscribe_on_stop: Bool = false
        var auto_retranscribe_during_recording: Bool = false
        var retranscribe_window_seconds: Int = 600
        var auto_analyze_on_complete: Bool = false
        var auto_analyze_modes: [String] = []
        var auto_analyze_custom_instructions: String = ""
        var auto_analyze_timing: String = "after"
        var live_transcription_by_default: Bool = true

        enum CodingKeys: String, CodingKey {
            case model_unload_delay, auto_paste, auto_close_on_paste, language
            case selected_model, widget_size, widget_position
            case auto_retranscribe_on_stop, auto_retranscribe_during_recording, retranscribe_window_seconds
            case auto_analyze_on_complete
            case auto_analyze_modes, auto_analyze_custom_instructions, auto_analyze_timing
            case live_transcription_by_default
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            model_unload_delay = try c.decode(Int.self, forKey: .model_unload_delay)
            auto_paste = try c.decode(Bool.self, forKey: .auto_paste)
            auto_close_on_paste = try c.decode(Bool.self, forKey: .auto_close_on_paste)
            language = try c.decode(String.self, forKey: .language)
            selected_model = try c.decode(String.self, forKey: .selected_model)
            widget_size = try c.decodeIfPresent(WidgetSize.self, forKey: .widget_size)
            widget_position = try c.decodeIfPresent(WidgetPosition.self, forKey: .widget_position)
            auto_retranscribe_on_stop = try c.decodeIfPresent(Bool.self, forKey: .auto_retranscribe_on_stop) ?? false
            auto_retranscribe_during_recording = try c.decodeIfPresent(Bool.self, forKey: .auto_retranscribe_during_recording) ?? false
            retranscribe_window_seconds = try c.decodeIfPresent(Int.self, forKey: .retranscribe_window_seconds) ?? 600
            auto_analyze_on_complete = try c.decodeIfPresent(Bool.self, forKey: .auto_analyze_on_complete) ?? false
            auto_analyze_modes = try c.decodeIfPresent([String].self, forKey: .auto_analyze_modes) ?? []
            auto_analyze_custom_instructions = try c.decodeIfPresent(String.self, forKey: .auto_analyze_custom_instructions) ?? ""
            auto_analyze_timing = try c.decodeIfPresent(String.self, forKey: .auto_analyze_timing) ?? "after"
            live_transcription_by_default = try c.decodeIfPresent(Bool.self, forKey: .live_transcription_by_default) ?? true
        }
    }
    
    /// Response wrapper for transcription settings
    struct TranscriptionSettingsResponse: Codable {
        let status: String
        let settings: TranscriptionSettings
    }
    
    // MARK: - System Audio State (macOS 14.0+)
    @available(macOS 14.0, *)
    var systemAudioState: SystemAudioState? {
        get { _systemAudioState as? SystemAudioState }
        set { 
            _systemAudioState = newValue
            if let state = newValue {
                // Set up observation of availableAudioProcesses
                state.$availableAudioProcesses
                    .sink { [weak self] processes in
                        self?.availableAudioProcesses = processes
                    }
                    .store(in: &cancellables)
                
                // Single observation point for process selection
                state.$selectedAudioProcess
                    .sink { [weak self] process in
                        guard let self = self else { return }
                        if let process = process {
                            #if DEBUG
                            DevLogger.shared.info("Process selection changed to: \(process.name)", context: "LiveTranscriptionViewModel")
                            #endif
                            
                            // Only set up audio tap if we're not recording and there isn't already a tap for this process
                            if !self.isRecording && (self.systemAudioState?.processTap?.process.id != process.id) {
                                self.setupSystemAudioTap(for: process)
                            }
                            
                            // Stop the process group timer when a process is selected
                            // We don't need to keep polling once a selection is made
                            self.processObserver?.cancel()
                            self.processObserver = nil
                            #if DEBUG
                            DevLogger.shared.info("Stopped process group polling timer (process selected)", context: "LiveTranscriptionViewModel")
                            #endif
                        } else {
                            // Restart the process group timer when no process is selected
                            // Only if we're showing the selection UI and NOT cleaning up
                            if self.processObserver == nil && self.isSystemAudioAvailable && !self.isCleaningUp {
                                #if DEBUG
                                DevLogger.shared.info("Restarting process group polling timer (no process selected)", context: "LiveTranscriptionViewModel")
                                #endif
                                self.setupProcessGroupTimer()
                            }
                        }
                    }
                    .store(in: &cancellables)
            }
        }
    }
    
    @available(macOS 14.0, *)
    var selectedAudioProcess: AudioProcess? {
        get { systemAudioState?.selectedAudioProcess }
        set {
            #if DEBUG
            DevLogger.shared.info("ViewModel selectedAudioProcess setter called with: \(newValue?.name ?? "None")", context: "LiveTranscriptionViewModel")
            #endif
            setSelectedAudioProcess(newValue)
        }
    }
    
    var isMicrophoneCaptureActive: Bool {
        isRecording && audioEngine?.isRunning == true
    }

    @available(macOS 14.0, *)
    var isSystemAudioCaptureActive: Bool {
        guard isRecording, let systemAudioState else {
            return false
        }
        return systemAudioState.processTapRecorder?.isRecording == true
            || systemAudioState.globalOutputRecorder?.isRecording == true
    }
    
    // MARK: - Initialization
    init() {
        // Generate default meeting name with timestamp
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        self.meetingName = "Meeting \(formatter.string(from: Date()))"
        
        // Restore sidebar state from storage
        self.isSidebarCollapsed = storedSidebarCollapsed
        
        if #available(macOS 14.0, *) {
            systemAudioState = SystemAudioState()
            systemAudioState?.audioProcessController = AudioProcessController()
            isSystemAudioAvailable = true
        }
    }
    
    // MARK: - Public Interface
    
    /// Toggle recording on/off
    func toggleRecording() {
        if isRecording {
            stopRecording()
        } else {
            startRecording()
        }
    }
    
    /// Pre-initialize the backend models to avoid delay when starting transcription
    func preinitializeBackendModels() async {
        #if DEBUG
        DevLogger.shared.info("Pre-initializing backend models...", context: "LiveTranscriptionViewModel")
        #endif
        
        guard let url = URL(string: "http://localhost:8000/whisper-live/initialize") else {
            #if DEBUG
            DevLogger.shared.error("Invalid pre-initialization URL", context: "LiveTranscriptionViewModel")
            #endif
            await MainActor.run {
                transcriptionState = .idle  // Fallback to idle even on error
                statusMessage = "Ready to start transcription"
            }
            return
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse else {
                #if DEBUG
                DevLogger.shared.error("Invalid HTTP response", context: "LiveTranscriptionViewModel")
                #endif
                await MainActor.run { 
                    transcriptionState = .idle
                    statusMessage = "Ready to start transcription"
                }
                return
            }
            
            #if DEBUG
            if let responseString = String(data: data, encoding: .utf8) {
                DevLogger.shared.info("Backend response (\(httpResponse.statusCode)): \(responseString)", context: "LiveTranscriptionViewModel")
            }
            #endif
            
            if httpResponse.statusCode == 200 {
                // Parse JSON response
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let status = json["status"] as? String {
                    #if DEBUG
                    DevLogger.shared.info("Backend models pre-initialized with status: \(status)", context: "LiveTranscriptionViewModel")
                    #endif
                    await MainActor.run {
                        transcriptionState = .idle  // Models loaded, now ready
                        statusMessage = "Ready to start transcription"
                    }
                } else {
                    #if DEBUG
                    DevLogger.shared.warning("Could not parse backend response, assuming success", context: "LiveTranscriptionViewModel")
                    #endif
                    await MainActor.run {
                        transcriptionState = .idle  // Assume success
                        statusMessage = "Ready to start transcription"
                    }
                }
            } else {
                #if DEBUG
                DevLogger.shared.error("Backend returned status \(httpResponse.statusCode)", context: "LiveTranscriptionViewModel")
                #endif
                await MainActor.run {
                    transcriptionState = .idle  // Fallback to idle
                    statusMessage = "Ready to start transcription"
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to pre-initialize backend models: \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
            #endif
            await MainActor.run {
                transcriptionState = .idle  // Fallback to idle on error
                statusMessage = "Ready to start transcription"
            }
        }
    }
    
    /// Initialize the ViewModel and set up system audio
    func initialize() async {
        #if DEBUG
        DevLogger.shared.info("Initializing LiveTranscriptionViewModel", context: "LiveTranscriptionViewModel")
        #endif
        
        // Set loading state immediately
        transcriptionState = .loadingModels
        statusMessage = "Loading models..."
        
        #if DEBUG
        DevLogger.shared.info("Set transcription state to loadingModels", context: "LiveTranscriptionViewModel")
        #endif
        
        // Pre-initialize backend models only when this meeting will transcribe live.
        await loadLiveTranscriptionDefault()
        if sessionLiveTranscriptionEnabled {
            await preinitializeBackendModels()
        } else {
            transcriptionState = .idle
            statusMessage = Self.recordOnlyIdleStatusMessage
        }
        
        if #available(macOS 14.0, *) {
            guard let controller = systemAudioState?.audioProcessController else {
                #if DEBUG
                DevLogger.shared.error("No AudioProcessController available", context: "LiveTranscriptionViewModel")
                #endif
                return
            }
            
            #if DEBUG
            DevLogger.shared.info("Activating AudioProcessController", context: "LiveTranscriptionViewModel")
            #endif
            
            controller.activate()
            
            // Fetch process groups immediately
            let groups = controller.processGroups
            #if DEBUG
            DevLogger.shared.info("Found \(groups.count) process groups:", context: "LiveTranscriptionViewModel")
            for group in groups {
                DevLogger.shared.info("  Group '\(group.title)' has \(group.processes.count) processes", context: "LiveTranscriptionViewModel")
            }
            #endif
            
            // Update the available processes
            availableAudioProcesses = groups
            
            // Start the process group timer
            setupProcessGroupTimer()
            
            // Now set up the rest of system audio
            setupSystemAudio()
        }
    }
    
    /// Clean up all resources when the view is being removed
    func cleanupAllResources() {
        #if DEBUG
        DevLogger.shared.info("cleanupAllResources() called - starting aggressive cleanup", context: "LiveTranscriptionViewModel")
        #endif
        
        // Set flag to prevent timer recreation
        isCleaningUp = true
        
        // Stop recording if active
        if isRecording {
            #if DEBUG
            DevLogger.shared.info("Stopping active recording before cleanup", context: "LiveTranscriptionViewModel")
            #endif
            // Closing the window while paused keeps the part but leaves it unprocessed.
            stopRecording(runPostStopActions: !isCapturePaused)
        }
        
        // AGGRESSIVELY cancel the process observer timer
        if let observer = processObserver {
            #if DEBUG
            DevLogger.shared.info("Canceling process observer timer", context: "LiveTranscriptionViewModel")
            #endif
            observer.cancel()
        }
        processObserver = nil
        
        updateMicrophoneAudioLevel(0.0)
        updateSystemAudioLevel(0.0)
        
        // AGGRESSIVELY cancel recording timer
        if let timer = timerCancellable {
            #if DEBUG
            DevLogger.shared.info("Canceling recording timer", context: "LiveTranscriptionViewModel")
            #endif
            timer.cancel()
        }
        timerCancellable = nil
        
        // Clear WebSocket references to avoid orphaned connections
        if let wsTask = microphoneWebSocketTask {
            #if DEBUG
            DevLogger.shared.info("Canceling microphone WebSocket task", context: "LiveTranscriptionViewModel")
            #endif
            wsTask.cancel()
        }
        microphoneWebSocketTask = nil
        
        if let wsTask = systemAudioWebSocketTask {
            #if DEBUG
            DevLogger.shared.info("Canceling system audio WebSocket task", context: "LiveTranscriptionViewModel")
            #endif
            wsTask.cancel()
        }
        systemAudioWebSocketTask = nil
        
        // Cancel any connection tasks
        if let connTask = connectionTask {
            #if DEBUG
            DevLogger.shared.info("Canceling connection task", context: "LiveTranscriptionViewModel")
            #endif
            connTask.cancel()
        }
        connectionTask = nil

        microphoneInputRecoveryTask?.cancel()
        microphoneInputRecoveryTask = nil
        microphoneWebSocketRecoveryTask?.cancel()
        microphoneWebSocketRecoveryTask = nil
        microphoneRecoveryGeneration &+= 1
        microphoneReconnectInFlight = false
        microphoneInputRecoveryState = .idle
        
        // Clear cached audio data
        if #available(macOS 14.0, *) {
            #if DEBUG
            DevLogger.shared.info("Cleaning up system audio resources", context: "LiveTranscriptionViewModel")
            #endif
            systemAudioState?.processTap?.invalidate()
            systemAudioState?.processTapRecorder?.stop()
            systemAudioState?.processTapRecorder = nil
            systemAudioState?.audioProcessController = nil
            systemAudioState?.systemAudioLevelObserver?.cancel()
            systemAudioState?.systemAudioLevelObserver = nil
        }
        
        // Reset audio engine and its configuration-change observer.
        stopMicrophoneAudioEngine()
        
        // AGGRESSIVELY clear ALL cancellables
        #if DEBUG
        DevLogger.shared.info("Canceling \(cancellables.count) remaining cancellables", context: "LiveTranscriptionViewModel")
        #endif
        cancellables.forEach { $0.cancel() }
        cancellables.removeAll()
        
        // Reset state flags
        isRecording = false
        connectionState = .ready
        
        #if DEBUG
        DevLogger.shared.info("✅ All resources cleaned up - cleanup complete", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Returns the process observer for cancellation
    func getProcessObserver() -> AnyCancellable? {
        return processObserver
    }
    
    // MARK: - Model Selection
    
    /// Load available transcription models from backend
    func loadAvailableModels() async {
        isLoadingModels = true
        
        let result = await TranscriptionModelOption.loadAll()
        let options = result.allOptions
        let models = options.map(\.displayName)

        await MainActor.run {
            self.availableModels = models
            self.transcriptionModelOptions = options
            self.isLoadingModels = false
            self.selectedModel = result.currentModelId

            if let selectedOption = options.first(where: { $0.id == result.currentModelId || $0.displayName == result.currentModelId }) {
                self.postProcessingModel = selectedOption.displayName
            } else if let firstModel = models.first {
                self.postProcessingModel = firstModel
            }
        }

        #if DEBUG
        DevLogger.shared.info("Loaded \(models.count) available transcription models, current selection: \(result.currentModelId), post-processing default: \(self.postProcessingModel)", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Update selected transcription model
    /// Note: Change takes effect on next recording start, not mid-session
    func updateSelectedModel(_ modelId: String) async {
        guard !isRecording else {
            #if DEBUG
            DevLogger.shared.warning("Cannot change model while recording is active", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        selectedModel = modelId
        
        do {
            try await APIClient.shared.updateSelectedTranscriptionModel(modelId)
            #if DEBUG
            DevLogger.shared.info("Updated transcription model to: \(modelId)", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to update transcription model: \(error)", context: "LiveTranscriptionViewModel")
            #endif
        }
    }
    
}
