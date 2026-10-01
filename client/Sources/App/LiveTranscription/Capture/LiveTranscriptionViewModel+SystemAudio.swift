import Foundation
import AVFoundation
import Combine

// MARK: - System Audio Management (macOS 14.0+)
@available(macOS 14.0, *)
extension LiveTranscriptionViewModel {
    
    /// Nested class for managing system audio state
    @MainActor
    final class SystemAudioState: ObservableObject {
        @Published var selectedAudioProcess: AudioProcess?
        @Published var availableAudioProcesses: [AudioProcessGroup] = []
        @Published var systemAudioLevel: Float = 0.0
        var audioProcessController: AudioProcessController?
        var processTap: ProcessTap?
        var processTapRecorder: ProcessTapRecorder?
        var globalOutputTap: SystemOutputTap?
        var globalOutputRecorder: SystemOutputTapRecorder?
        let meterState = SystemAudioMeterState()
        var systemAudioLevelObserver: AnyCancellable?
        var sentSystemAudioChunkCount: UInt64 = 0
        /// Set while capture is paused with the system tap stopped; resume writes new segments into this folder.
        var pausedBackupDirectory: URL?
        /// The tapped process to restore on resume; nil while paused means global output capture.
        var pausedProcess: AudioProcess?
        private var lastSelectedProcessId: pid_t?
        private var allowOneMoreUpdate: Bool = false
        
        init() {
            audioProcessController = AudioProcessController()
        }
        
        func updateAvailableProcesses(_ processes: [AudioProcessGroup]) {
            // First update available processes
            availableAudioProcesses = processes
            
            // Then try to restore selection if needed
            if selectedAudioProcess == nil, let lastId = lastSelectedProcessId {
                let allProcesses = processes.flatMap { $0.processes }
                if let matchingProcess = allProcesses.first(where: { $0.id == lastId }) {
                    #if DEBUG
                    DevLogger.shared.info("Restoring selected process: \(matchingProcess.name) (ID: \(matchingProcess.id))", context: "SystemAudioState")
                    #endif
                    DispatchQueue.main.async {
                        self.selectedAudioProcess = matchingProcess
                    }
                }
            }
            
            // If this was the one allowed update after selection, prevent further updates
            if !allowOneMoreUpdate && selectedAudioProcess != nil {
                #if DEBUG
                DevLogger.shared.info("Preventing further process list updates after selection", context: "SystemAudioState")
                #endif
                return
            }
            
            // Reset the flag after using it
            if allowOneMoreUpdate {
                allowOneMoreUpdate = false
            }
        }
        
        func setSelectedProcess(_ process: AudioProcess?) {
            if let process = process {
                #if DEBUG
                DevLogger.shared.info("Setting selected process to: \(process.name) (ID: \(process.id))", context: "SystemAudioState")
                #endif
                lastSelectedProcessId = process.id
                allowOneMoreUpdate = true  // Allow one more update after selection
            } else {
                #if DEBUG
                DevLogger.shared.info("Clearing selected process", context: "SystemAudioState")
                #endif
                lastSelectedProcessId = nil
            }
            
            DispatchQueue.main.async {
                self.selectedAudioProcess = process
            }
        }
    }
    
    /// Initializes system audio controller and starts process discovery
    @MainActor
    func setupSystemAudio() {
        #if DEBUG
        DevLogger.shared.info("Initializing audio process controller", context: "LiveTranscription")
        #endif
        
        guard let controller = systemAudioState?.audioProcessController else {
            #if DEBUG
            DevLogger.shared.error("No AudioProcessController available", context: "LiveTranscription")
            #endif
            return
        }
        
        #if DEBUG
        DevLogger.shared.info("Activating AudioProcessController", context: "LiveTranscription")
        #endif
        
        controller.activate()
        
        // Initial fetch of process groups
        let groups = controller.processGroups
        #if DEBUG
        DevLogger.shared.info("Initial fetch - found \(groups.count) process groups", context: "LiveTranscriptionViewModel")
        #endif
        
        // Update available processes through the state (which will trigger the published property update)
        systemAudioState?.updateAvailableProcesses(groups)
        
        // Start the process group timer
        setupProcessGroupTimer()
        
        #if DEBUG
        DevLogger.shared.info("Starting process group fetch task", context: "LiveTranscription")
        #endif
    }
    
    /// Creates and activates a process tap for the selected audio process
    @MainActor
    func setupSystemAudioTap(for process: AudioProcess) {
        #if DEBUG
        DevLogger.shared.info("Setting up system audio tap for process: \(process.name)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Create a new tap for the selected process
        let newTap = ProcessTap(process: process)
        systemAudioState?.processTap = newTap
        newTap.activate()
        
        #if DEBUG
        DevLogger.shared.info("ProcessTap activated and ready for \(process.name) (PID: \(process.id))", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Starts recording system audio from the selected process
    func startSystemAudioRecording() async throws {
        #if DEBUG
        DevLogger.shared.info("CRITICAL: Inside startSystemAudioRecording() function", context: "LiveTranscriptionViewModel")
        #endif
        
        var processTap = systemAudioState?.processTap
        if let selectedProcess = selectedAudioProcess,
           let existingTap = processTap,
           existingTap.process.id != selectedProcess.id {
            #if DEBUG
            DevLogger.shared.warning("Discarding process tap for \(existingTap.process.name); selected process is \(selectedProcess.name)", context: "LiveTranscriptionViewModel")
            #endif
            existingTap.invalidate()
            systemAudioState?.processTap = nil
            processTap = nil
        }

        if let existingTap = processTap, !existingTap.activated {
            #if DEBUG
            DevLogger.shared.warning("Discarding inactive process tap for \(existingTap.process.name)", context: "LiveTranscriptionViewModel")
            #endif
            systemAudioState?.processTap = nil
            processTap = nil
        }

        if processTap == nil, let selectedProcess = selectedAudioProcess {
            #if DEBUG
            DevLogger.shared.info("Creating fresh process tap for \(selectedProcess.name) before recording", context: "LiveTranscriptionViewModel")
            #endif
            setupSystemAudioTap(for: selectedProcess)
            processTap = systemAudioState?.processTap
        }

        guard let processTap else {
            #if DEBUG
            DevLogger.shared.warning("Cannot start system audio recording - no process tap available", context: "LiveTranscriptionViewModel")
            #endif
            throw AudioError.engineSetupFailed
        }
        
        // First, establish a dedicated WebSocket connection for system audio
        try await startSystemAudioWebSocketConnection(processName: processTap.process.name)
        try await sendNativeStreamTimingControl(for: .systemAudio)
        
        // Create a recording directory if needed
        let recordingsDirectory = URL.documentsDirectory.appendingPathComponent("Basil/Recordings/\(UUID().uuidString)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: recordingsDirectory, withIntermediateDirectories: true)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to create recordings directory: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            throw error
        }

        try startProcessTapRecorder(for: processTap, in: recordingsDirectory)
    }

    /// Returns a backup WAV path in `directory` that does not overwrite an earlier segment of the same recording.
    nonisolated static func systemAudioBackupFileURL(in directory: URL, baseName: String) -> URL {
        let timestamp = Int(Date.now.timeIntervalSince1970)
        let candidate = directory.appendingPathComponent("\(baseName)-\(timestamp).wav")
        guard FileManager.default.fileExists(atPath: candidate.path) else { return candidate }
        return directory.appendingPathComponent("\(baseName)-\(timestamp)-\(UUID().uuidString.prefix(8)).wav")
    }

    /// Starts writing and streaming the selected-process tap into `recordingsDirectory`; the system-audio socket must already be open.
    func startProcessTapRecorder(for processTap: ProcessTap, in recordingsDirectory: URL) throws {
        let audioFileURL = Self.systemAudioBackupFileURL(in: recordingsDirectory, baseName: processTap.process.name)
        
        #if DEBUG
        DevLogger.shared.info("Creating system audio recorder with output file: \(audioFileURL.path)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Create the recorder
        let newRecorder = ProcessTapRecorder(fileURL: audioFileURL, tap: processTap)
        systemAudioState?.processTapRecorder = newRecorder
        
        #if DEBUG
        DevLogger.shared.info("Created ProcessTapRecorder for \(processTap.process.name)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Set up the audio data callback
        newRecorder.onAudioDataAvailable = { [weak self] audioData in
            self?.sendSystemAudioFloatData(audioData)
        }
        newRecorder.onRecordingFailure = { [weak self, weak newRecorder] message in
            Task { @MainActor [weak self, weak newRecorder] in
                guard let self else { return }
                guard self.systemAudioState?.processTapRecorder === newRecorder else { return }
                self.handleSelectedProcessRecorderFailure(message)
            }
        }
        
        // Set up the audio level observer
        systemAudioState?.meterState.reset()
        updateSystemAudioLevel(0.0)
        systemAudioState?.systemAudioLevelObserver = newRecorder.$audioLevel
            .receive(on: RunLoop.main)
            .sink { [weak self] level in
                self?.systemAudioState?.systemAudioLevel = level
                if let meterState = self?.systemAudioState?.meterState {
                    self?.updateSystemAudioLevel(meterState.filteredLevel(for: level))
                }
                
                // Log audio levels occasionally
                #if DEBUG
                if Int.random(in: 1...30) == 1 {
                    DevLogger.shared.info("🔊 Current audio level: \(level)", context: "LiveTranscriptionViewModel")
                }
                #endif
            }
        
        // Start recording
        do {
            #if DEBUG
            DevLogger.shared.info("Starting ProcessTapRecorder", context: "LiveTranscriptionViewModel")
            #endif
            
            try newRecorder.start()
            
            #if DEBUG
            DevLogger.shared.info("System audio recording started successfully", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to start system audio recording: \(error)", context: "LiveTranscriptionViewModel")
            DevLogger.shared.error("CRITICAL ERROR: \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
            #endif
            
            throw error
        }
    }

    func sendSystemAudioFloatData(_ audioData: Data) {
        let captureEndElapsed = recordingClock.elapsedSeconds()
        let floatData = audioData.withUnsafeBytes { $0.bindMemory(to: Float32.self) }
        guard floatData.count > 0 else { return }

        // Clamp to [-1, 1] and guard against NaN/inf before scaling: the
        // Int16(_:) initializer traps on out-of-range or non-finite values,
        // and CoreAudio float samples are not guaranteed to be normalized.
        var int16Data = Data(capacity: audioData.count / 2)
        for sample in floatData {
            let safeSample = sample.isFinite ? min(1.0, max(-1.0, sample)) : 0.0
            let int16Sample = Int16(safeSample * 32767.0)
            int16Data.append(contentsOf: withUnsafeBytes(of: int16Sample) { Array($0) })
        }

        let chunkSize = 3200
        var offset = 0
        while offset < int16Data.count {
            let length = min(chunkSize, int16Data.count - offset)
            let chunk = int16Data.subdata(in: offset..<(offset + length))
            // 16 kHz mono Int16 is 32,000 bytes per second of audio.
            let chunkStartElapsed = max(0, captureEndElapsed - Double(int16Data.count - offset) / 32000.0)

            DispatchQueue.main.async { [weak self] in
                guard let self = self, self.isRecording else { return }
                // While a reconnect is in flight the task is nil; skip sending
                // (the loop effectively pauses) rather than spawning more reconnects.
                guard !self.systemAudioReconnectInFlight else { return }
                guard !self.isCapturePaused else { return }
                guard self.systemAudioStreamTimingReady else { return }
                guard let systemAudioWebSocketTask = self.systemAudioWebSocketTask else {
                    #if DEBUG
                    DevLogger.shared.warning("Cannot send system audio chunk: System audio WebSocket not connected", context: "LiveTranscriptionViewModel")
                    #endif
                    if self.connectionState == .recording || self.connectionState == .connecting {
                        self.recoverSystemAudioWebSocket(reason: "socket not connected")
                    }
                    return
                }

                if self.recordingClock.claimMarker(for: .systemAudio, at: chunkStartElapsed) {
                    systemAudioWebSocketTask.send(.string(LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: chunkStartElapsed))) { _ in }
                }
                systemAudioWebSocketTask.send(.data(chunk)) { error in
                    if let error {
                        #if DEBUG
                        DevLogger.shared.error("❌ Failed to send system audio chunk: \(error)", context: "LiveTranscriptionViewModel")
                        #endif
                        // The socket is dead. Recover (debounced) so the stream
                        // continues instead of logging ~10 failures/sec forever.
                        Task { @MainActor [weak self] in
                            self?.recoverSystemAudioWebSocket(reason: "send failed: \(error.localizedDescription)")
                        }
                    } else {
                        Task { @MainActor [weak self] in
                            guard let self else { return }
                            self.lastBufferSendTime = Date().timeIntervalSince1970
                            if self.systemAudioCaptureMode == .globalOutput {
                                let nextCount = (self.systemAudioState?.sentSystemAudioChunkCount ?? 0) + 1
                                self.systemAudioState?.sentSystemAudioChunkCount = nextCount
                                #if DEBUG
                                if nextCount == 1 || nextCount % 100 == 0 {
                                    DevLogger.shared.info(
                                        "Global system audio websocket sent chunk \(nextCount) (\(chunk.count) bytes)",
                                        context: "LiveTranscriptionViewModel"
                                    )
                                }
                                #endif
                            }
                        }
                    }
                }
            }

            offset += length
        }
    }

    func startGlobalSystemAudioRecording() async throws {
        guard #available(macOS 14.2, *) else {
            throw "Global system output capture requires macOS 14.2 or later"
        }

        try await startSystemAudioWebSocketConnection(sourceName: "System Audio")
        try await sendNativeStreamTimingControl(for: .systemAudio)
        systemAudioState?.sentSystemAudioChunkCount = 0

        let recordingsDirectory = URL.documentsDirectory.appendingPathComponent("Basil/Recordings/\(UUID().uuidString)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: recordingsDirectory, withIntermediateDirectories: true)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to create recordings directory: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            throw error
        }

        try startGlobalOutputRecorder(in: recordingsDirectory)
    }

    /// Creates the global output tap and starts writing and streaming it into `recordingsDirectory`; the system-audio socket must already be open.
    func startGlobalOutputRecorder(in recordingsDirectory: URL) throws {
        let audioFileURL = Self.systemAudioBackupFileURL(in: recordingsDirectory, baseName: "SystemAudio")

        let tap = SystemOutputTap()
        systemAudioState?.globalOutputTap = tap
        tap.activate()
        if let errorMessage = tap.errorMessage {
            throw errorMessage
        }

        #if DEBUG
        DevLogger.shared.info("Global system audio tap activated; preparing recorder", context: "LiveTranscriptionViewModel")
        #endif

        let recorder = SystemOutputTapRecorder(fileURL: audioFileURL, tap: tap)
        systemAudioState?.globalOutputRecorder = recorder
        recorder.onAudioDataAvailable = { [weak self] audioData in
            self?.sendSystemAudioFloatData(audioData)
        }
        systemAudioState?.meterState.reset()
        updateSystemAudioLevel(0.0)
        systemAudioState?.systemAudioLevelObserver = recorder.$audioLevel
            .receive(on: RunLoop.main)
            .sink { [weak self] level in
                self?.systemAudioState?.systemAudioLevel = level
                if let meterState = self?.systemAudioState?.meterState {
                    self?.updateSystemAudioLevel(meterState.filteredLevel(for: level))
                }
            }

        try recorder.start()

        #if DEBUG
        DevLogger.shared.info("Global system audio recorder started successfully at \(audioFileURL.path)", context: "LiveTranscriptionViewModel")
        #endif
    }

    /// Stops the system-audio tap for a pause. The socket stays open so resuming does not reconnect, and the backup folder is kept so resumed segments land beside the first one.
    func suspendSystemAudioCapture() {
        guard let state = systemAudioState else { return }
        let activeFile = state.processTapRecorder?.fileURL ?? state.globalOutputRecorder?.fileURL
        guard let activeFile else { return }
        state.pausedBackupDirectory = activeFile.deletingLastPathComponent()
        state.pausedProcess = state.processTapRecorder != nil ? state.processTap?.process : nil

        state.processTapRecorder?.stop()
        state.processTapRecorder = nil
        // The invalidated process tap stays in state so a socket reconnect during the pause still knows the process name.
        state.processTap?.invalidate()
        state.globalOutputRecorder?.stop()
        state.globalOutputRecorder = nil
        state.globalOutputTap?.invalidate()
        state.globalOutputTap = nil

        state.systemAudioLevelObserver?.cancel()
        state.systemAudioLevelObserver = nil
        state.systemAudioLevel = 0.0
        state.meterState.reset()
        updateSystemAudioLevel(0.0)
    }

    /// Restarts the system-audio tap stopped by `suspendSystemAudioCapture`, writing a new backup segment into the same folder.
    func resumeSystemAudioCapture() throws {
        guard let state = systemAudioState, let directory = state.pausedBackupDirectory else { return }
        let process = state.pausedProcess
        state.pausedBackupDirectory = nil
        state.pausedProcess = nil

        if let process {
            setupSystemAudioTap(for: process)
            guard let processTap = state.processTap, processTap.activated else {
                throw AudioError.engineSetupFailed
            }
            try startProcessTapRecorder(for: processTap, in: directory)
        } else {
            try startGlobalOutputRecorder(in: directory)
        }
    }

    @MainActor
    func handleSelectedProcessRecorderFailure(_ message: String) {
        #if DEBUG
        DevLogger.shared.warning("Selected-process recorder failure: \(message)", context: "LiveTranscriptionViewModel")
        #endif

        systemAudioState?.processTapRecorder?.stop()
        systemAudioState?.processTapRecorder = nil

        systemAudioState?.systemAudioLevelObserver?.cancel()
        systemAudioState?.systemAudioLevelObserver = nil

        if let tap = systemAudioState?.processTap {
            #if DEBUG
            DevLogger.shared.info("Invalidating selected-process tap after recorder failure for \(tap.process.name)", context: "LiveTranscriptionViewModel")
            #endif
            tap.invalidate()
            systemAudioState?.processTap = nil
        }

        systemAudioWebSocketTask?.cancel()
        systemAudioWebSocketTask = nil

        systemAudioState?.systemAudioLevel = 0.0
        systemAudioState?.meterState.reset()
        updateSystemAudioLevel(0.0)
        systemAudioState?.sentSystemAudioChunkCount = 0
        statusMessage = "Recording microphone only. \(message)"
    }
    
    /// Stops system audio recording and cleans up resources
    func stopSystemAudioRecording() {
        #if DEBUG
        DevLogger.shared.info("Stopping system audio recording", context: "LiveTranscriptionViewModel")
        #endif
        
        // Add logs to track cleanup state
        #if DEBUG
        DevLogger.shared.info("Stopping process tap recorder", context: "LiveTranscriptionViewModel")
        #endif
        
        // First stop the recorder
        systemAudioState?.processTapRecorder?.stop()
        systemAudioState?.processTapRecorder = nil
        systemAudioState?.globalOutputRecorder?.stop()
        systemAudioState?.globalOutputRecorder = nil
        
        #if DEBUG
        DevLogger.shared.info("Canceling system audio level observer", context: "LiveTranscriptionViewModel")
        #endif
        
        // Cancel audio level observer 
        systemAudioState?.systemAudioLevelObserver?.cancel()
        systemAudioState?.systemAudioLevelObserver = nil
        
        // Deactivate the process tap
        if let tap = systemAudioState?.processTap {
            #if DEBUG
            DevLogger.shared.info("Invalidating process tap for \(tap.process.name)", context: "LiveTranscriptionViewModel")
            #endif
            tap.invalidate()
            // Invalidated taps cannot be reused by the next recording session.
            systemAudioState?.processTap = nil
        }
        systemAudioState?.globalOutputTap?.invalidate()
        systemAudioState?.globalOutputTap = nil
        systemAudioState?.pausedBackupDirectory = nil
        systemAudioState?.pausedProcess = nil
        
        // Reset the audio level
        if let state = systemAudioState {
            state.systemAudioLevel = 0.0
            state.meterState.reset()
            updateSystemAudioLevel(0.0)
            state.sentSystemAudioChunkCount = 0
            systemAudioState = state
        }
        
        #if DEBUG
        DevLogger.shared.info("System audio recording stopped completely", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Sets the selected audio process for system audio capture
    func setSelectedAudioProcess(_ process: AudioProcess?) {
        #if DEBUG
        DevLogger.shared.info("ViewModel setSelectedAudioProcess called with: \(process?.name ?? "None")", context: "LiveTranscriptionViewModel")
        #endif
        
        if process != nil {
            systemAudioCaptureMode = .selectedProcess
        }

        // Update the state
        systemAudioState?.setSelectedProcess(process)
        
        // Force a UI update by reassigning the published property
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.objectWillChange.send()
        }
    }
    
    /// Sets up periodic polling for available audio processes
    func setupProcessGroupTimer() {
        // Don't create timer if we're cleaning up
        guard !isCleaningUp else {
            #if DEBUG
            DevLogger.shared.info("Skipping timer setup - cleanup in progress", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        // Cancel any existing timer
        processObserver?.cancel()
        
        // Create new timer to fetch process groups
        processObserver = Timer.publish(every: 1, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                guard let self = self, !self.isCleaningUp else { return }
                
                guard let controller = self.systemAudioState?.audioProcessController else { return }
                
                let groups = controller.processGroups
                // Commenting out noisy timer logs - uncomment for debugging process selection issues
                // #if DEBUG
                // DevLogger.shared.info("Timer update - found \(groups.count) groups", context: "LiveTranscriptionViewModel")
                // #endif
                
                // Use the new update method instead of direct assignment
                self.systemAudioState?.updateAvailableProcesses(groups)
            }
    }
    
}

