import Foundation
import Combine

extension TranscriptionWidgetViewModel {
    @MainActor
    func initialize(autoStartRecording: Bool = false) async {
        // Prevent redundant initialization if already properly initialized
        if isConnected && isModelReady && !isModelLoading {
            print("⚠️ TranscriptionWidgetViewModel already initialized, skipping duplicate call")
            return
        }
        
        print("\n🎯 Initializing TranscriptionWidgetViewModel")
        error = nil
        isModelReady = false
        isModelLoading = false
        transitionRecordingLifecycle(to: .idle)
        pendingAutoStartRecording = autoStartRecording
        let settings = APIClient.shared.getCachedTranscriptionSettings()
        isMinimized = settings.isWidgetMinimized
        #if DEBUG
        DevLogger.shared.info("Loaded minimized state from settings: \(isMinimized)", context: "TranscriptionWidget")
        #endif
        setupSubscriptions(autoStartRecording: autoStartRecording)
        Task { [weak self] in
            await self?.audioCaptureController.prepareRecordingPipelineIfAuthorized()
        }
        // Kick off the transcription model list fetch in parallel with
        // the WebSocket bring-up. The picker is non-critical UI -- if it
        // fails to load the dropdown is just empty and the widget still
        // works. We don't block the initialization sequence on it.
        Task { [weak self] in
            await self?.loadAvailableTranscriptionModels()
        }
        do {
            print("🌐 Starting WebSocket connection...")
            try await startListening()
            print("✅ WebSocket connection established")
            if pendingAutoStartRecording {
                pendingAutoStartRecording = false
                await startRecording()
            }
        } catch {
            pendingAutoStartRecording = false
            isModelLoading = false
            print("❌ Initialization failed with error: \(error)")
            self.error = "Initialization failed: \(error.localizedDescription)"
            transcriptionText = "Initialization failed"
        }
    }

    func setupSubscriptions(autoStartRecording: Bool = false) {
        print("\n🔄 Setting up subscriptions")
        cancellables.removeAll()
        print("✨ Cleared existing subscriptions")
        let subscription = webSocketService.eventSubject
            .filter { event in
                // Only handle transcription-related events
                switch event {
                case .transcriptionStarted, .transcriptionProgress, .transcriptionCompleted, .transcriptionFailed, .transcriptionCanceled, .connectionStateChanged, .modelReady:
                    return true
                default:
                    return false
                }
            }
            .sink { [weak self] event in
                Task { @MainActor in
                    #if DEBUG
                    DevLogger.shared.info("WebSocket event received: \(event)", context: "websocket")
                    #endif
                    switch event {
                    case .transcriptionStarted:
                        HotkeyService.shared.beginTranscriptionHotkeySuppression()
                        // Only set "Recording in progress..." if we're actually still recording
                        // This prevents late-arriving events from overwriting "Processing transcription..."
                        guard self?.isRecording == true else {
                            #if DEBUG
                            DevLogger.shared.info("Ignoring transcriptionStarted event - not recording", context: "text_state")
                            #endif
                            return
                        }
                        #if DEBUG
                        DevLogger.shared.info("Transcription started - Setting text to 'Recording in progress...'", context: "text_state")
                        #endif
                        self?.transcriptionText = "Recording in progress..."
                        self?.pulseScale = 1.5
                    case .transcriptionProgress(let payload):
                        guard self?.recordingLifecycle == .processing else { return }
                        if let message = payload["message"] as? String, !message.isEmpty {
                            self?.transcriptionText = message
                        } else if let current = payload["current_time_seconds"] as? Double,
                                  let duration = payload["audio_duration_seconds"] as? Double,
                                  duration > 0 {
                            self?.transcriptionText = String(
                                format: "Transcribing with Parakeet: %.1fs / %.1fs",
                                current,
                                duration
                            )
                        }
                    case .transcriptionCanceled:
                        #if DEBUG
                        DevLogger.shared.info("Transcription canceled - Resetting UI without processing text", context: "text_state")
                        #endif
                        HotkeyService.shared.endTranscriptionHotkeySuppression()
                        self?.transcriptionText = "Recording canceled"
                        self?.pulseScale = 1.0
                        self?.transitionRecordingLifecycle(to: .idle)
                        Task { @MainActor in
                            do {
                                try await Task.sleep(nanoseconds: 1_500_000_000)
                                self?.transcriptionText = "Ready to record"
                            } catch {
                                #if DEBUG
                                DevLogger.shared.error("Error during delay: \(error)", context: "text_state")
                                #endif
                            }
                        }
                    case .transcriptionCompleted(let text):
                        #if DEBUG
                        DevLogger.shared.info("Transcription completed - Setting new text", context: "text_state")
                        #endif
                        self?.transcriptionText = text
                        self?.pulseScale = 1.0
                        self?.transitionRecordingLifecycle(to: .idle)
                        HotkeyService.shared.endTranscriptionHotkeySuppression()
                        Task { @MainActor [weak self] in
                            if self != nil {
                                #if DEBUG
                                DevLogger.shared.info("Auto-close check - TranscriptionWidget exists", context: "auto_close")
                                #endif
                                let settings = APIClient.shared.getCachedTranscriptionSettings()
                                #if DEBUG
                                DevLogger.shared.info("Auto-close check - Settings retrieved: autoPaste=\(settings.autoPaste), autoCloseOnPaste=\(settings.autoCloseOnPaste)", context: "auto_close")
                                DevLogger.shared.info("Force refreshing settings from server", context: "auto_close")
                                #endif
                                do {
                                    let data = try await APIClient.shared.get("/settings/transcription")
                                    if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
                                        #if DEBUG
                                        DevLogger.shared.info("Fresh settings from server: autoPaste=\(response.settings.autoPaste), autoCloseOnPaste=\(response.settings.autoCloseOnPaste)", context: "auto_close")
                                        #endif
                                        let freshSettings = response.settings
                                        APIClient.shared.cacheTranscriptionSettings(freshSettings)
                                        if freshSettings.autoPaste && freshSettings.autoCloseOnPaste {
                                            #if DEBUG
                                            DevLogger.shared.info("Auto-close-on-paste is enabled, closing widget after a short delay...", context: "auto_close")
                                            #endif
                                            do {
                                                #if DEBUG
                                                DevLogger.shared.info("Auto-close - Starting delay...", context: "auto_close")
                                                #endif
                                                try await Task.sleep(nanoseconds: 250_000_000)
                                                #if DEBUG
                                                DevLogger.shared.info("Auto-close - Delay completed, posting notification", context: "auto_close")
                                                #endif
                                                NotificationCenter.default.post(
                                                    name: NSNotification.Name("CloseTranscriptionWidgetRequest"),
                                                    object: nil,
                                                    userInfo: ["reason": "recording canceled"]
                                                )
                                                #if DEBUG
                                                DevLogger.shared.info("Auto-close - Notification posted", context: "auto_close")
                                                #endif
                                            } catch {
                                                #if DEBUG
                                                DevLogger.shared.error("Auto-close - Error during delay: \(error)", context: "auto_close")
                                                #endif
                                            }
                                        } else {
                                            #if DEBUG
                                            DevLogger.shared.info("Auto-close check - Conditions not met (fresh settings), widget will remain open", context: "auto_close")
                                            #endif
                                        }
                                    }
                                } catch {
                                    #if DEBUG
                                    DevLogger.shared.error("Failed to get fresh settings: \(error)", context: "auto_close")
                                    DevLogger.shared.info("Falling back to cached settings", context: "auto_close")
                                    #endif
                                    if settings.autoPaste && settings.autoCloseOnPaste {
                                        #if DEBUG
                                        DevLogger.shared.info("Auto-close-on-paste is enabled (cached), closing widget after a short delay...", context: "auto_close")
                                        #endif
                                        do {
                                            try await Task.sleep(nanoseconds: 250_000_000)
                                            NotificationCenter.default.post(
                                                name: NSNotification.Name("CloseTranscriptionWidgetRequest"),
                                                object: nil,
                                                userInfo: ["reason": "recording canceled"]
                                            )
                                        } catch {
                                            #if DEBUG
                                            DevLogger.shared.error("Auto-close - Error during delay: \(error)", context: "auto_close")
                                            #endif
                                        }
                                    } else {
                                        #if DEBUG
                                        DevLogger.shared.info("Auto-close check - Conditions not met (cached), widget will remain open", context: "auto_close")
                                        #endif
                                    }
                                }
                            } else {
                                #if DEBUG
                                DevLogger.shared.info("Auto-close check - TranscriptionWidget no longer exists", context: "auto_close")
                                #endif
                            }
                        }
                    case .transcriptionFailed(let error):
                        #if DEBUG
                        DevLogger.shared.error("Transcription failed: \(error)", context: "text_state")
                        #endif
                        let modelFailedDuringRecording = self?.isModelLoading == true
                            && self?.recordingLifecycle == .recording
                        self?.error = "Error: \(error)"
                        self?.pulseScale = 1.0
                        self?.isModelLoading = false
                        self?.pendingAutoStartRecording = false
                        HotkeyService.shared.endTranscriptionHotkeySuppression()
                        if !modelFailedDuringRecording {
                            self?.transitionRecordingLifecycle(to: .failed)
                        }
                    case .connectionStateChanged(let connected):
                        print("🔌 Connection state changed: \(connected)")
                        self?.handleTranscriptionConnectionStateChange(connected)
                    case .modelReady:
                        print("✅ Model ready event received")
                        self?.isModelReady = true
                        self?.isModelLoading = false
                    default:
                        // This should never be reached due to the filter above
                        break
                    }
                }
            }
        print("📥 Adding WebSocket event subscription to cancellables")
        cancellables.insert(subscription)
        let connectionSubscription = webSocketService.$isConnected
            .sink { [weak self] connected in
                Task { @MainActor in
                    print("🔌 Connection state changed: \(connected)")
                    self?.handleTranscriptionConnectionStateChange(connected)
                }
            }
        print("📥 Adding connection state subscription to cancellables")
        cancellables.insert(connectionSubscription)
        audioCaptureService.$isRecording
            .dropFirst()
            .sink { [weak self] recording in
                Task { @MainActor in
                    guard let self = self,
                          !recording,
                          self.recordingLifecycle == .recording else { return }
                    self.error = self.audioCaptureService.error ?? "Microphone recording was interrupted."
                    self.transcriptionText = "Ready to record"
                    self.pulseScale = 1.0
                    self.transitionRecordingLifecycle(to: .failed)
                }
            }
            .store(in: &cancellables)
        let audioLevelSubscription = audioCaptureService.$audioLevel
            .sink { [weak self] level in
                Task { @MainActor in
                    self?.updateAudioLevel(level)
                }
            }
        print("📥 Adding audio level subscription to cancellables")
        cancellables.insert(audioLevelSubscription)
        let errorSubscription = audioCaptureService.$error
            .sink { [weak self] error in
                Task { @MainActor in
                    guard let error = error else { return }
                    print("❌ Audio capture error: \(error)")
                    self?.error = error
                }
            }
        print("📥 Adding error subscription to cancellables")
        cancellables.insert(errorSubscription)
    }

    func handleTranscriptionConnectionStateChange(_ connected: Bool) {
        isConnected = connected
        guard !connected else { return }

        HotkeyService.shared.endTranscriptionHotkeySuppression()
        pendingAutoStartRecording = false
        isModelReady = false
        isModelLoading = false
        switch recordingLifecycle {
        case .starting:
            cancelRecordingStartup()
            error = "Connection lost before microphone recording started."
            transitionRecordingLifecycle(to: .failed)
        case .recording:
            audioCaptureController.stopRecording(sendAudioData: false, flowContext: nil, context: nil)
            error = "Connection lost before transcription could be sent."
            transitionRecordingLifecycle(to: .failed)
        case .processing:
            error = "Connection lost before transcription completed."
            transitionRecordingLifecycle(to: .failed)
        case .idle, .failed:
            break
        }
        transcriptionText = "Disconnected from server..."
    }

    func startListening() async throws {
        print("🔌 Starting WebSocket connection...")
        transcriptionText = "Connecting to server..."
        webSocketService.connect()
        try await withTimeout(seconds: 5) { [self] in
            await withCheckedContinuation { continuation in
                self.webSocketService.$isConnected
                    .filter { $0 }
                    .first()
                    .sink { _ in
                        print("🌐 WebSocket connected")
                        continuation.resume()
                    }
                    .store(in: &self.cancellables)
            }
        }
        print("🎯 Initializing transcription model")
        transcriptionText = "Loading transcription model..."
        isModelLoading = true
        try await webSocketService.initializeTranscription()
        print("✅ Transcription model initialization request sent")
    }

    func withTimeout<T>(seconds: TimeInterval, operation: @escaping () async -> T) async throws -> T {
        try await withThrowingTaskGroup(of: T.self) { group in
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                throw WebSocketService.WebSocketError.connectionTimeout
            }
            group.addTask {
                return await operation()
            }
            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }

    func stopListening() {
        cleanup()  // Use comprehensive cleanup
    }
}

