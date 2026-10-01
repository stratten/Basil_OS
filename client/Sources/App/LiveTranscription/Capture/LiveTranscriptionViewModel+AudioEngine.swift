import Foundation
import AVFoundation
import Combine

// MARK: - Audio Engine Management
extension LiveTranscriptionViewModel {
    
    /// Initializes and configures the audio engine for microphone capture
    func setupAudioEngine() throws {
        #if DEBUG
        DevLogger.shared.info("[AUDIO ENGINE] setupAudioEngine called. Current engine pointer: \(audioEngine != nil ? String(describing: Unmanaged.passUnretained(audioEngine!).toOpaque()) : "nil")", context: "LiveTranscriptionViewModel")
        #endif
        let newAudioEngine = AVAudioEngine()
        audioEngine = newAudioEngine
        installMicrophoneEngineConfigurationObserver(for: newAudioEngine)
        #if DEBUG
        DevLogger.shared.info("[AUDIO ENGINE] New AVAudioEngine instance created at pointer: \(Unmanaged.passUnretained(newAudioEngine).toOpaque())", context: "LiveTranscriptionViewModel")
        DevLogger.shared.info("[AUDIO ENGINE] Input node pointer: \(Unmanaged.passUnretained(newAudioEngine.inputNode).toOpaque())", context: "LiveTranscriptionViewModel")
        #endif
        let audioEngine = newAudioEngine
        let input = audioEngine.inputNode
        let nativeFormat = input.inputFormat(forBus: 0)
        
        // Create target format: 16kHz, mono, Int16
        let targetFormat = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                       sampleRate: 16000,
                                       channels: 1,
                                       interleaved: true)!
        
        #if DEBUG
        DevLogger.shared.info("Native format: \(nativeFormat)", context: "LiveTranscriptionViewModel")
        DevLogger.shared.info("Target format: \(targetFormat)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Seed the rate estimator fresh for this recording part (setupAudioEngine()
        // runs once per part, including a resumed part's own new engine/tap), so a
        // prior part's throughput measurement never leaks into this one. A resumed
        // meeting's prior-segment duration is a separate, already-handled concern:
        // it is applied server-side via timeline_offset_seconds/native_stream_timing,
        // independent of this part's own capture-rate correction.
        microphoneRateEstimator.reset(declaredSampleRate: nativeFormat.sampleRate)
        
        // Converter is rebuilt below whenever the rate estimator's corrected input
        // rate changes (e.g. once it confirms the true rate differs from the
        // declared nativeFormat - see AudioInputRateEstimator), mirroring
        // AudioStreamResampler's lazy-rebuild-on-format-change behavior.
        var converter = AVAudioConverter(from: nativeFormat, to: targetFormat)
        var converterInputSampleRate = nativeFormat.sampleRate
        
        // Buffer size for 100ms of audio at 16kHz (same as HTML version)
        let bufferSize = 1600 // 16000 Hz * 0.1 seconds = 1600 samples
        
        input.installTap(onBus: 0, bufferSize: AVAudioFrameCount(bufferSize), format: nativeFormat) { [weak self] buffer, time in
            // Removed excessive logging that was firing on every audio buffer
            guard let self = self else { return }
            
            // Correct for a declared input format that doesn't match the true
            // capture rate (e.g. an aggregate device clocked by a Bluetooth
            // headset - see AudioInputRateEstimator). In the common case the
            // estimate equals the declared rate and this is a no-op.
            let estimatedRate = self.microphoneRateEstimator.observe(frameCount: buffer.frameLength)
            let bufferForConversion: AVAudioPCMBuffer
            if estimatedRate != buffer.format.sampleRate,
               let relabeled = buffer.relabeled(sampleRate: estimatedRate) {
                bufferForConversion = relabeled
            } else {
                bufferForConversion = buffer
            }
            
            if converter == nil || converterInputSampleRate != bufferForConversion.format.sampleRate {
                converter = AVAudioConverter(from: bufferForConversion.format, to: targetFormat)
                converterInputSampleRate = bufferForConversion.format.sampleRate
            }
            
            // Create output buffer. Sized from the actual (possibly rate-corrected)
            // input frame count so a corrected ratio never overflows a capacity
            // that assumed the nominal declared rate.
            let outputCapacity = AVAudioFrameCount(
                (Double(bufferForConversion.frameLength) * (targetFormat.sampleRate / bufferForConversion.format.sampleRate)).rounded(.up)
            ) + 32
            let outputBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat,
                                              frameCapacity: outputCapacity)!
            
            var error: NSError?
            
            // Convert buffer
            let inputBlock: AVAudioConverterInputBlock = { inNumPackets, outStatus in
                outStatus.pointee = .haveData
                return bufferForConversion
            }
            
            converter?.convert(to: outputBuffer,
                             error: &error,
                             withInputFrom: inputBlock)
            
            if let error = error {
                #if DEBUG
                DevLogger.shared.error("[AUDIO ENGINE] Conversion error: \(error)", context: "LiveTranscriptionViewModel")
                #endif
                return
            }
            
            // Get the raw int16 samples
            guard let int16Data = outputBuffer.int16ChannelData?[0] else { return }

            let microphoneLevel = AudioLevelNormalizer.normalizedLevel(
                from: UnsafeBufferPointer(
                    start: int16Data,
                    count: Int(outputBuffer.frameLength)
                )
            )
            DispatchQueue.main.async {
                self.updateMicrophoneAudioLevel(microphoneLevel)
            }
            
            // Create Data from the int16 samples and send immediately
            let data = Data(bytes: int16Data,
                          count: Int(outputBuffer.frameLength) * MemoryLayout<Int16>.stride)
            
            // Send to dedicated microphone WebSocket
            guard self.microphoneStreamTimingReady else { return }
            // Periodic clock markers pin this socket's samples to the meeting clock so live timestamps never drift.
            let captureStartElapsed = max(0, self.recordingClock.elapsedSeconds() - Double(outputBuffer.frameLength) / 16000.0)
            if self.recordingClock.claimMarker(for: .microphone, at: captureStartElapsed) {
                self.microphoneWebSocketTask?.send(.string(LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: captureStartElapsed))) { _ in }
            }
            self.microphoneWebSocketTask?.send(.data(data)) { error in
                if let error = error {
                    DispatchQueue.main.async {
                        #if DEBUG
                        DevLogger.shared.error("[AUDIO ENGINE] Failed to send microphone audio data: \(error)", context: "LiveTranscriptionViewModel")
                        #endif
                        // Recover the mic socket directly (mirrors the system-audio
                        // send-failure path in LiveTranscriptionViewModel+SystemAudio.swift)
                        // instead of routing through handleError()'s generic,
                        // unattributed-source branch. This call site already knows
                        // unambiguously that the microphone socket is the one that
                        // died, so recovering it directly means a healthy system-audio
                        // stream is never disturbed by a mic-only send failure.
                        self.recoverMicrophoneWebSocket(reason: "send failed: \(error.localizedDescription)")
                    }
                }
            }
        }
        
        #if DEBUG
        DevLogger.shared.info("[AUDIO ENGINE] Audio engine setup completed with buffer size: \(bufferSize) frames", context: "LiveTranscriptionViewModel")
        #endif
        
        try audioEngine.start()
        #if DEBUG
        DevLogger.shared.info("[AUDIO ENGINE] audioEngine.start() called. Engine pointer: \(Unmanaged.passUnretained(audioEngine).toOpaque())", context: "LiveTranscriptionViewModel")
        #endif
    }

    private func installMicrophoneEngineConfigurationObserver(for engine: AVAudioEngine) {
        removeMicrophoneEngineConfigurationObserver()
        let engineIdentifier = ObjectIdentifier(engine)
        microphoneEngineConfigurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self,
                      let activeEngine = self.audioEngine,
                      ObjectIdentifier(activeEngine) == engineIdentifier else { return }
                self.recoverMicrophoneCaptureAfterDeviceChange()
            }
        }
    }

    private func removeMicrophoneEngineConfigurationObserver() {
        if let microphoneEngineConfigurationObserver {
            NotificationCenter.default.removeObserver(microphoneEngineConfigurationObserver)
            self.microphoneEngineConfigurationObserver = nil
        }
    }

    func stopMicrophoneAudioEngine() {
        removeMicrophoneEngineConfigurationObserver()
        guard let audioEngine else { return }
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        self.audioEngine = nil
    }

    func retryMicrophoneCaptureAfterDeviceChange() {
        recoverMicrophoneCaptureAfterDeviceChange()
    }

    private func recoverMicrophoneCaptureAfterDeviceChange() {
        guard isRecording, enableMicrophone, microphoneInputRecoveryTask == nil else { return }
        let supersededWebSocketRecoveryTask = microphoneWebSocketRecoveryTask
        supersededWebSocketRecoveryTask?.cancel()
        microphoneWebSocketRecoveryTask = nil
        connectionTask?.cancel()
        microphoneWebSocketTask?.cancel()
        microphoneRecoveryGeneration &+= 1
        let recoveryGeneration = microphoneRecoveryGeneration
        microphoneReconnectInFlight = true
        microphoneInputRecoveryState = .reconnecting
        statusMessage = "Microphone changed. Reconnecting..."
        if !isSystemAudioStillCapturing {
            connectionState = .connecting
        }

        microphoneInputRecoveryTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.microphoneRecoveryGeneration == recoveryGeneration {
                    self.microphoneReconnectInFlight = false
                    self.microphoneInputRecoveryTask = nil
                }
            }

            await supersededWebSocketRecoveryTask?.value
            guard self.microphoneRecoveryGeneration == recoveryGeneration,
                  self.isRecording,
                  !Task.isCancelled else { return }
            self.stopMicrophoneAudioEngine()
            self.microphoneWebSocketTask?.cancel()
            self.microphoneWebSocketTask = nil

            do {
                try await self.reconnectWebSocket()
                guard self.microphoneRecoveryGeneration == recoveryGeneration,
                      self.isRecording,
                      !Task.isCancelled else { return }
                if !self.isCapturePaused {
                    try self.setupAudioEngine()
                }
                self.microphoneInputRecoveryState = .idle
                self.connectionState = .recording
                self.statusMessage = self.recordingStatusMessage()
            } catch {
                guard self.microphoneRecoveryGeneration == recoveryGeneration,
                      self.isRecording,
                      !Task.isCancelled else { return }
                self.stopMicrophoneAudioEngine()
                self.microphoneInputRecoveryState = .failed(message: error.localizedDescription)
                self.connectionState = self.isSystemAudioStillCapturing ? .recording : .error
                self.statusMessage = "Microphone unavailable. Retry microphone to continue capture."
            }
        }
    }

    private var isSystemAudioStillCapturing: Bool {
        if #available(macOS 14.0, *) {
            return isSystemAudioCaptureActive
        }
        return false
    }
    
    /// Starts recording session with microphone and optional system audio
    func startRecording() {
        guard !isRecording else { return }
        
        // A normal (non-resume) start must never reuse a prior meeting's identity.
        // Resume arms `.resume` via prepareResumeRecordingSession() before calling
        // this; every other path mints a brand-new meeting so a Stop -> Start (or
        // stale history selection) can't overwrite an existing recording.
        if recordingMode != .resume {
            prepareFreshRecordingSession()
        }
        
        // Validate that at least one audio source is enabled
        let hasSystemAudioSelected = if #available(macOS 14.0, *) {
            isSystemAudioAvailable && (selectedAudioProcess != nil || systemAudioCaptureMode == .globalOutput)
        } else {
            false
        }
        
        guard enableMicrophone || hasSystemAudioSelected else {
            #if DEBUG
            DevLogger.shared.warning("Cannot start recording: No audio sources enabled", context: "LiveTranscriptionViewModel")
            #endif
            Task { @MainActor in
                statusMessage = "Please enable at least one audio source"
            }
            return
        }
        
        Task {
            do {
                #if DEBUG
                DevLogger.shared.info("Starting live transcription recording", context: "LiveTranscriptionViewModel")
                DevLogger.shared.info("Microphone enabled: \(enableMicrophone)", context: "LiveTranscriptionViewModel")
                #endif
                
                if #available(macOS 14.0, *) {
                    if let process = selectedAudioProcess {
                        #if DEBUG
                        DevLogger.shared.info("Selected audio process: \(process.name) (PID: \(process.id))", context: "LiveTranscriptionViewModel")
                        #endif
                    } else {
                        #if DEBUG
                        DevLogger.shared.info("No audio process selected", context: "LiveTranscriptionViewModel")
                        #endif
                    }
                }
                
                await MainActor.run {
                    connectionState = .connecting
                    statusMessage = "Connecting to server..."
                }
                
                // First fetch settings
                try await fetchTranscriptionSettings()

                await MainActor.run {
                    isRecording = true
                    recordingStartTime = Date()
                    recordingClock.start()
                    isCapturePaused = false
                    liveTranscriptionWasDisabledThisPart = !sessionLiveTranscriptionEnabled
                    startTimer()
                }

                // Microphone and system audio use independent sockets/taps, so
                // connect both concurrently instead of strictly sequentially.
                // The pre-recording wait used to be the SUM of the mic
                // connection wait and the system audio setup (including a
                // flat 500ms sleep on that side); now it's roughly the MAX of
                // the two, which is what actually made the ready -> recording
                // transition feel sluggish even for API-backed models that
                // require no local model loading.
                async let microphoneConnect: Void = connectMicrophoneForRecording()
                async let systemAudioConnect: String? = connectSystemAudioForRecording()

                try await microphoneConnect
                if let softErrorMessage = try await systemAudioConnect {
                    await MainActor.run {
                        statusMessage = softErrorMessage
                    }
                }
                
                // Set up audio engine only if microphone is enabled
                if enableMicrophone {
                #if DEBUG
                    DevLogger.shared.info("Setting up audio engine for microphone", context: "LiveTranscriptionViewModel")
                #endif
                
                try setupAudioEngine()
                } else {
                    #if DEBUG
                    DevLogger.shared.info("Microphone disabled, skipping audio engine setup", context: "LiveTranscriptionViewModel")
                    #endif
                }
                
                await MainActor.run {
                    isRecording = true
                    connectionState = .recording
                    statusMessage = recordingStatusMessage()
                    startRetranscribeCadence()
                    NotificationCenter.default.post(name: .liveTranscriptionRecordingDidStart, object: nil)
                }
                
                // Refresh meeting history so the new meeting appears in the sidebar
                await loadMeetingHistory()
                
                #if DEBUG
                DevLogger.shared.info("Recording started successfully", context: "LiveTranscriptionViewModel")
                #endif
                
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to start recording: \(error)", context: "LiveTranscriptionViewModel")
                DevLogger.shared.error("CRITICAL ERROR: \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
                #endif
                await MainActor.run {
                    if isRecording {
                        stopRecording()
                    }
                    updateMicrophoneAudioLevel(0.0)
                    connectionState = .error
                    handleError(error)
                }
            }
        }
    }

    /// Establishes the microphone WebSocket connection if microphone capture
    /// is enabled; a no-op otherwise. Split out of startRecording() so it can
    /// run concurrently with connectSystemAudioForRecording() via async-let.
    private func connectMicrophoneForRecording() async throws {
        guard enableMicrophone else {
            #if DEBUG
            DevLogger.shared.info("Microphone disabled, skipping microphone WebSocket connection", context: "LiveTranscriptionViewModel")
            #endif
            return
        }

        #if DEBUG
        DevLogger.shared.info("CRITICAL: About to start microphone WebSocket connection", context: "LiveTranscriptionViewModel")
        #endif

        try await startListening()
        try await sendNativeStreamTimingControl(for: .microphone)

        #if DEBUG
        DevLogger.shared.info("CRITICAL: Microphone WebSocket connection established", context: "LiveTranscriptionViewModel")
        #endif
    }

    /// Establishes system audio capture if available/selected. Returns a
    /// soft-failure status message when `.globalOutput` capture couldn't
    /// start but recording should continue microphone-only (mirroring the
    /// previous inline soft-fail behavior); throws only when there's no
    /// microphone fallback to fall back to. Split out of startRecording() so
    /// it can run concurrently with connectMicrophoneForRecording() via
    /// async-let.
    private func connectSystemAudioForRecording() async throws -> String? {
        #if DEBUG
        DevLogger.shared.info("Starting system audio recording setup", context: "LiveTranscriptionViewModel")
        DevLogger.shared.info("System audio available: \(isSystemAudioAvailable)", context: "LiveTranscriptionViewModel")
        #endif

        guard isSystemAudioAvailable else {
            #if DEBUG
            DevLogger.shared.warning("System audio is not available", context: "LiveTranscriptionViewModel")
            #endif
            return nil
        }

        if #available(macOS 14.0, *), systemAudioCaptureMode == .globalOutput {
            do {
                try await startGlobalSystemAudioRecording()
                #if DEBUG
                DevLogger.shared.info("Global system audio recording started successfully", context: "LiveTranscriptionViewModel")
                #endif
                return nil
            } catch {
                #if DEBUG
                DevLogger.shared.error("Global system audio recording failed: \(error)", context: "LiveTranscriptionViewModel")
                #endif
                if enableMicrophone {
                    return "Recording microphone only. System audio could not start: \(error.localizedDescription)"
                } else {
                    throw error
                }
            }
        } else if #available(macOS 14.0, *), let process = selectedAudioProcess {
            #if DEBUG
            DevLogger.shared.info("System audio is available and process selected, proceeding with setup", context: "LiveTranscriptionViewModel")
            DevLogger.shared.info("Starting system audio recording for process: \(process.name)", context: "LiveTranscriptionViewModel")
            DevLogger.shared.info("CRITICAL: About to call startSystemAudioRecording()", context: "LiveTranscriptionViewModel")
            #endif

            try await startSystemAudioRecording()

            #if DEBUG
            DevLogger.shared.info("System audio recording started successfully", context: "LiveTranscriptionViewModel")
            #endif
            return nil
        } else {
            #if DEBUG
            if #available(macOS 14.0, *) {
                DevLogger.shared.info("No system audio process selected, using microphone only", context: "LiveTranscriptionViewModel")
            } else {
                DevLogger.shared.warning("macOS 14.0+ required for system audio recording", context: "LiveTranscriptionViewModel")
            }
            #endif
            return nil
        }
    }

    /// Stops recording and cleans up audio resources
    func stopRecording(runPostStopActions: Bool = true) {
        #if DEBUG
        DevLogger.shared.info("Stopping live transcription recording", context: "LiveTranscriptionViewModel")
        DevLogger.shared.info("[AUDIO ENGINE] stopRecording called. Engine pointer: \(audioEngine != nil ? String(describing: Unmanaged.passUnretained(audioEngine!).toOpaque()) : "nil")", context: "LiveTranscriptionViewModel")
        #endif
        
        // Stop system audio recording if active
        if #available(macOS 14.0, *) {
            stopSystemAudioRecording()
        }
        
        // Terminate both WebSocket connections (microphone and system audio)
        let terminateWebSocket: (URLSessionWebSocketTask, String) -> Void = { task, label in
            Task {
                do {
                    try await task.send(.string("{\"action\":\"force_terminate\",\"reason\":\"shutdown\"}"))
                    
                    #if DEBUG
                    DevLogger.shared.info("\(label) websocket termination messages sent", context: "LiveTranscriptionViewModel")
                    #endif
                } catch {
                    let errorDescription = error.localizedDescription
                    let isExpectedShutdownError = errorDescription.contains("Socket is not connected") ||
                                                  errorDescription.contains("Operation canceled")
                    
                    #if DEBUG
                    if isExpectedShutdownError {
                        DevLogger.shared.info("\(label) websocket was already closed during shutdown", context: "LiveTranscriptionViewModel")
                    } else {
                        DevLogger.shared.error("Error in \(label) websocket termination: \(error)", context: "LiveTranscriptionViewModel")
                    }
                    #endif
                }
                
                task.cancel(with: .normalClosure, reason: nil)
                
                #if DEBUG
                DevLogger.shared.info("\(label) WebSocket task canceled", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
        
        // Terminate microphone WebSocket if active
        if let micTask = microphoneWebSocketTask {
            terminateWebSocket(micTask, "Microphone")
        }
        microphoneWebSocketTask = nil
        
        // Terminate system audio WebSocket if active
        if let sysTask = systemAudioWebSocketTask {
            terminateWebSocket(sysTask, "System Audio")
        }
        systemAudioWebSocketTask = nil
        
        // Stop the connection tasks if they're still running
        connectionTask?.cancel()
        connectionTask = nil
        systemAudioConnectionTask?.cancel()
        systemAudioConnectionTask = nil
        
        microphoneInputRecoveryTask?.cancel()
        microphoneInputRecoveryTask = nil
        microphoneWebSocketRecoveryTask?.cancel()
        microphoneWebSocketRecoveryTask = nil
        microphoneRecoveryGeneration &+= 1
        microphoneReconnectInFlight = false
        microphoneReconnectAttempt = 0
        systemAudioReconnectAttempt = 0
        microphoneInputRecoveryState = .idle
        stopMicrophoneAudioEngine()
        recordingClock.stop()
        isCapturePaused = false

        // Reset recording state
        isRecording = false
        connectionState = .ready
        
        // Consume any resume arming so the next Start is a fresh meeting by default.
        // Meeting ids are intentionally left intact here for post-processing.
        recordingMode = .fresh
        resumeTimelineOffsetSeconds = 0.0
        recordingPartIndex = 0
        resumedFromMeetingId = nil
        microphoneStreamTimingReady = false
        systemAudioStreamTimingReady = false
        
        // Mark that we have recorded audio (for post-processing UI)
        // Always set to true after recording, even if meeting wasn't saved
        hasRecordedAudio = true
        
        // If live transcription produced any text, mark hasTranscription as true
        // This allows post-processing operations like diarization to proceed
        if !transcriptionLines.isEmpty {
            hasTranscription = true
        }
        
        // Cancel all timers
        timerCancellable?.cancel()
        timerCancellable = nil
        
        // Cancel global line break timer
        globalLineBreakTimer?.cancel()
        globalLineBreakTimer = nil

        // Stop the mid-recording re-transcription cadence (checkpoints are kept so
        // the on-stop tail pass knows where cadence left off).
        stopRetranscribeCadence()
        
        updateMicrophoneAudioLevel(0.0)
        
        // Cancel process group polling if we're not using system audio
        // We only need to keep this running if system audio is available and we need to show process selection
        if !isSystemAudioAvailable {
            processObserver?.cancel()
            processObserver = nil
            #if DEBUG
            DevLogger.shared.info("Stopped process group polling timer (system audio not available)", context: "LiveTranscriptionViewModel")
            #endif
        } else if #available(macOS 14.0, *), selectedAudioProcess == nil {
            // If system audio is available but no process is selected, we don't need constant updates
            // Only restart the timer if the user opens the process selection UI
            processObserver?.cancel()
            processObserver = nil
            #if DEBUG
            DevLogger.shared.info("Stopped process group polling timer (no process selected)", context: "LiveTranscriptionViewModel")
            #endif
        }
        
        statusMessage = "Ready to start transcription"
        
        #if DEBUG
        DevLogger.shared.info("Recording stopped completely", context: "LiveTranscriptionViewModel")
        #endif

        let liveTranscriptionWasDisabled = liveTranscriptionWasDisabledThisPart
        liveTranscriptionWasDisabledThisPart = false
        // Cancel (and closing the window while paused) skips post-processing and the auto-view of the part.
        guard runPostStopActions else { return }

        triggerStopAutomationIfNeeded(forceRetranscribe: liveTranscriptionWasDisabled)

        // Drop into read-only viewing of the meeting just recorded so the
        // Resume / Start New controls appear instead of a bare Start button.
        autoViewJustFinishedSession()
    }

    /// Kick off any configured post-stop automation (auto-retranscribe and/or
    /// auto-analyze) once recording has fully stopped. Honors the per-session
    /// overrides seeded from the global defaults; ordering of analysis vs.
    /// re-transcription follows the configured timing.
    private func triggerStopAutomationIfNeeded(forceRetranscribe: Bool = false) {
        // A part recorded (even partly) without live transcription has no complete transcript until it is re-transcribed.
        let autoRetranscribe = PostProcessingAutomation.shouldAutoRetranscribeOnStop(
            enabled: sessionAutoRetranscribeOnStop || forceRetranscribe,
            hasRecordedAudio: hasRecordedAudio
        )
        if forceRetranscribe && sessionAutoAnalyzeOnComplete {
            sessionAutoAnalyzeTiming = "after"
        }
        let plan = PostProcessingAutomation.plan(
            autoRetranscribe: autoRetranscribe,
            autoAnalyze: sessionAutoAnalyzeOnComplete,
            timing: sessionAutoAnalyzeTiming
        )
        guard !plan.isEmpty else { return }

        // When mid-recording cadence ran, only the tail since the last checkpoint
        // remains un-upgraded; otherwise a full re-transcription pass is needed.
        let cadenceRan = sessionAutoRetranscribeDuringRecording
            && lastRetranscribeCheckpointByMeeting.values.contains { $0 > 0 }
        let finishedSessionId = sessionId
        let finishedMeetingIds = Set(
            [microphoneMeetingId, systemAudioMeetingId].compactMap { $0 }
        )

        #if DEBUG
        DevLogger.shared.info("Post-stop automation plan: \(plan) (cadenceRan=\(cadenceRan))", context: "LiveTranscriptionViewModel")
        #endif

        Task { [weak self] in
            guard let self = self else { return }
            var didRetranscribe = false
            for step in plan {
                switch step {
                case .analyze:
                    // An analyze that follows a retranscribe is the "after"
                    // analysis, which the retranscribe step already runs in its
                    // finalize block; skip it here to avoid a duplicate run.
                    // A "before" analyze (no prior retranscribe) runs now.
                    if didRetranscribe { continue }
                    await self.runAutoAnalyze()
                case .retranscribe:
                    if cadenceRan {
                        // Tail-only upgrade, then the "after" analysis (mirrors
                        // startPostProcessing, which the full path uses instead).
                        self.postProcessingStartedAutomatically = true
                        let didCompleteTailRetranscription = await self.performOnStopTailRetranscription()
                        if didCompleteTailRetranscription {
                            await self.reloadJustFinishedMeetingAfterTailRetranscription(
                                sessionId: finishedSessionId,
                                meetingIds: finishedMeetingIds
                            )
                        }
                        if self.sessionAutoAnalyzeOnComplete && self.sessionAutoAnalyzeTiming == "after" {
                            await self.runAutoAnalyze()
                        }
                    } else {
                        await self.startPostProcessing(operation: "transcribe", startedAutomatically: true)
                    }
                    didRetranscribe = true
                }
            }
        }
    }

    /// Reconcile the just-finished live view with the canonical transcript after
    /// the final windowed tail has been persisted and replayed by the backend.
    private func reloadJustFinishedMeetingAfterTailRetranscription(
        sessionId: String?,
        meetingIds: Set<String>
    ) async {
        guard !meetingIds.isEmpty, !isRecording, isViewingPastMeeting else { return }

        await loadMeetingHistory()

        guard !isRecording, isViewingPastMeeting, let selectedMeetingId else { return }
        let representative = sessionId.flatMap { sessionId in
            meetings.first(where: { $0.sessionId == sessionId })
        }
        let isViewingFinishedMeeting = meetingIds.contains(selectedMeetingId)
            || representative?.id == selectedMeetingId
        guard isViewingFinishedMeeting else { return }

        await selectMeeting(representative?.id ?? selectedMeetingId)
    }
}

