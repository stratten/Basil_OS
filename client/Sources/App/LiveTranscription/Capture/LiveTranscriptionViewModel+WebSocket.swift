import Foundation
import Combine

// MARK: - WebSocket Management
extension LiveTranscriptionViewModel {
    
    /// Normalizes whitespace in transcription text
    /// - Removes multiple consecutive spaces
    /// - Removes spaces before punctuation
    /// - Ensures proper spacing after punctuation
    func normalizeWhitespace(_ text: String) -> String {
        var normalized = text
        
        // Remove multiple consecutive spaces
        normalized = normalized.replacingOccurrences(of: "  +", with: " ", options: .regularExpression)
        
        // Remove spaces before punctuation: , . ! ? ; : ) ] }
        normalized = normalized.replacingOccurrences(of: " +([,.!?;:)\\]}])", with: "$1", options: .regularExpression)
        
        // Ensure single space after punctuation if followed by a letter/digit (but not if at end)
        normalized = normalized.replacingOccurrences(of: "([,.!?;:])([A-Za-z0-9])", with: "$1 $2", options: .regularExpression)
        
        // Remove spaces after opening punctuation: ( [ {
        normalized = normalized.replacingOccurrences(of: "([\\(\\[{]) +", with: "$1", options: .regularExpression)
        
        return normalized.trimmingCharacters(in: .whitespaces)
    }
    
    /// Establishes WebSocket connection for microphone audio
    func startListening() async throws {
        guard let settings = transcriptionSettings else {
            throw WebSocketError.invalidSettings
        }
        
        // Generate microphone meeting ID
        if microphoneMeetingId == nil {
            microphoneMeetingId = UUID().uuidString
        }
        
        // Generate one shared session ID for this meeting (links mic + system audio).
        // Whichever socket opens first creates it; the other reuses it.
        if sessionId == nil {
            sessionId = UUID().uuidString
        }
        
        // Construct URL for microphone connection
        var components = URLComponents(string: websocketUrl)
        var queryItems = [
            URLQueryItem(name: "model", value: settings.selected_model),
            URLQueryItem(name: "language", value: settings.language),
            URLQueryItem(name: "client", value: "native")  // Specify native client
        ]
        
        // Add meeting information for microphone
        if !meetingName.isEmpty {
            queryItems.append(URLQueryItem(name: "meeting_id", value: microphoneMeetingId))
            queryItems.append(URLQueryItem(name: "meeting_name", value: "\(meetingName) - Microphone"))
            
            if !meetingPurpose.isEmpty {
                queryItems.append(URLQueryItem(name: "meeting_purpose", value: meetingPurpose))
            }
            
            if !meetingParticipants.isEmpty {
                queryItems.append(URLQueryItem(name: "meeting_participants", value: meetingParticipants))
            }
            
            // Always set audio source to "Microphone" for this connection
            queryItems.append(URLQueryItem(name: "audio_source", value: "Microphone"))
            
            // Link this recording to its session sibling (system audio)
            if let sessionId = sessionId {
                queryItems.append(URLQueryItem(name: "session_id", value: sessionId))
            }
            
            // Resume continuation context (placed on the logical meeting timeline).
            queryItems.append(contentsOf: resumeRecordingQueryItems())

            // Auto-reconnect of an in-progress part: tell the backend to append to
            // the existing recording rather than refuse or truncate it.
            if microphoneReconnectInFlight {
                queryItems.append(URLQueryItem(name: "reconnect", value: "true"))
            }
        }
        
        components?.queryItems = queryItems
        
        guard let url = components?.url else {
            #if DEBUG
            DevLogger.shared.error("Invalid microphone WebSocket URL: \(websocketUrl)", context: "LiveTranscriptionViewModel")
            #endif
            throw WebSocketError.invalidURL
        }
        
        #if DEBUG
        DevLogger.shared.info("Connecting microphone WebSocket with model: \(settings.selected_model), language: \(settings.language), meeting: \(meetingName) - Microphone", context: "LiveTranscriptionViewModel")
        #endif
        
        let session = URLSession(configuration: .default)
        microphoneStreamTimingReady = false
        microphoneWebSocketTask = session.webSocketTask(with: url)
        
        // Create a flag to track if we've received the first message
        var receivedFirstMessage = false
        
        // Start WebSocket connection
        microphoneWebSocketTask?.resume()
        
        #if DEBUG
        DevLogger.shared.info("Microphone WebSocket resumed, waiting for connection", context: "LiveTranscriptionViewModel")
        #endif
        
        // Start receiving messages with a completion handler that will also signal our continuation
        microphoneWebSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            switch result {
            case .success(let message):
                // Process the message
                Task { @MainActor in
                    self.handleWebSocketMessage(message)
                    
                    // Check if this is the first message and we need to signal the connection
                    if !receivedFirstMessage {
                        receivedFirstMessage = true
                        
                        #if DEBUG
                        DevLogger.shared.info("First microphone WebSocket message received, connection successful", context: "LiveTranscriptionViewModel")
                        #endif
                        
                        // Signal the connection task
                        self.connectionTask?.cancel()
                    }
                    
                    // Continue receiving microphone messages
                    self.receiveMicrophoneMessages()
                }
                
            case .failure(let error):
                #if DEBUG
                DevLogger.shared.error("WebSocket receive error: \(error)", context: "LiveTranscriptionViewModel")
                #endif
                
                // Signal the connection task with an error
                Task { @MainActor [weak self] in
                    self?.connectionError = error
                    self?.connectionTask?.cancel()
                }
            }
        }
        
        // Create a task that will be cancelled when the first message is received
        connectionError = nil
        connectionTask = Task {
            do {
                // Wait for up to 30 seconds for a message (model loading can take 15-20 seconds)
                try await Task.sleep(nanoseconds: 30_000_000_000)
                
                // If we get here, the timeout occurred
                throw NSError(domain: "com.basil.websocket", code: -1, userInfo: [NSLocalizedDescriptionKey: "WebSocket connection timeout"])
            } catch is CancellationError {
                // Check if we were cancelled due to an error
                if let error = connectionError {
                    throw error
                }
                
                // Otherwise we were cancelled because we received a message - success!
                #if DEBUG
                DevLogger.shared.info("Microphone WebSocket connection established successfully", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
        
        // Wait for the connection task to complete (either by timeout or by being cancelled)
        try await connectionTask?.value
        
        #if DEBUG
        DevLogger.shared.info("Microphone WebSocket connection established successfully, function complete", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Continuous message reception loop for microphone audio
    func receiveMicrophoneMessages() {
        microphoneWebSocketTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                Task { @MainActor [weak self] in
                    self?.handleMicrophoneMessage(message)
                    self?.receiveMicrophoneMessages() // Continue receiving messages
                }
                
            case .failure(let error):
                Task { @MainActor [weak self] in
                    self?.handleError(error, source: .microphone)
                }
            }
        }
    }
    
    /// Continuous message reception loop for system audio
    func receiveSystemAudioMessages() {
        systemAudioWebSocketTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                Task { @MainActor [weak self] in
                    self?.handleSystemAudioMessage(message)
                    self?.receiveSystemAudioMessages() // Continue receiving messages
                }
                
            case .failure(let error):
                Task { @MainActor [weak self] in
                    self?.handleError(error, source: .systemAudio)
                }
            }
        }
    }
    
    /// Handles incoming WebSocket messages
    @MainActor
    func handleWebSocketMessage(_ message: URLSessionWebSocketTask.Message) {
        #if DEBUG
        // Only log every 10th message to reduce noise (10% of messages)
        messageLogCounter += 1
        if messageLogCounter % 10 == 1 {
            switch message {
            case .string(let text):
                DevLogger.shared.info("WebSocket message #\(messageLogCounter): \(text.prefix(100))...", context: "LiveTranscriptionViewModel")
            case .data(let data):
                if let text = String(data: data, encoding: .utf8) {
                    DevLogger.shared.info("WebSocket data message #\(messageLogCounter): \(text.prefix(100))...", context: "LiveTranscriptionViewModel")
                } else {
                    DevLogger.shared.info("WebSocket binary data #\(messageLogCounter): \(data.count) bytes", context: "LiveTranscriptionViewModel")
                }
            @unknown default:
                DevLogger.shared.info("Unknown WebSocket message type #\(messageLogCounter)", context: "LiveTranscriptionViewModel")
            }
        }
        #endif

        // Then process the message
        switch message {
        case .string(let text):
            processTranscriptionMessage(text)
            
        case .data(let data):
            if let text = String(data: data, encoding: .utf8) {
                processTranscriptionMessage(text)
            }
            
        @unknown default:
            break
        }
    }
    
    /// Processes transcription messages from WebSocket
    func processTranscriptionMessage(_ text: String) {
        // Try to decode even if it doesn't contain "lines" - it might be a status update or other message type
        guard let data = text.data(using: .utf8),
              let response = try? JSONDecoder().decode(LiveTranscriptionResponse.self, from: data) else {
            #if DEBUG
            DevLogger.shared.error("Failed to decode message - invalid JSON format: \(text)", context: "LiveTranscriptionViewModel")
            #endif
            return
        }

        DispatchQueue.main.async { [weak self] in
            #if DEBUG
            // Log the full response details including speaker information and event-driven state
            let hasLines = !response.lines.isEmpty
            let hasBuffer = !(response.buffer_transcription?.isEmpty ?? true)
            let hasDiarization = !(response.buffer_diarization?.isEmpty ?? true)
            
            // Extract speaker information from lines
            let speakerIds = Set(response.lines.compactMap { $0.speakerNumber })
            let speakerInfo = speakerIds.isEmpty ? "None" : "Speakers: \(speakerIds.sorted().map { "Speaker \($0)" }.joined(separator: ", "))"
            
            DevLogger.shared.info("""
                Processing transcription response:
                - 🎯 State: \(response.state ?? "unknown")
                - 🕐 Accumulated: \(response.accumulated_duration ?? 0)s
                - 🎬 Trigger: \(response.trigger_reason ?? "none")
                - Lines: \(response.lines.count) (non-empty: \(hasLines))
                - 🎤 Speaker Attribution: \(speakerInfo)
                - Buffer: \(response.buffer_transcription ?? "nil") (non-empty: \(hasBuffer))
                - Diarization: \(response.buffer_diarization ?? "nil") (non-empty: \(hasDiarization))
                - Remaining time (trans/diar): \(response.remaining_time_transcription)/\(response.remaining_time_diarization)
                """, context: "LiveTranscriptionViewModel")
            
            // Log individual lines with speaker information for detailed debugging
            if hasLines {
                for (index, line) in response.lines.enumerated() {
                    let speakerLabel = line.speakerNumber.map { "Speaker \($0)" } ?? line.speakerID ?? "Unattributed"
                    DevLogger.shared.debug("  Line \(index + 1): [\(speakerLabel)] \(line.text.prefix(50))...", context: "LiveTranscriptionViewModel")
                }
            }
            #endif

            // Update event-driven state
            if let stateString = response.state {
                if let state = TranscriptionState(rawValue: stateString) {
                    self?.transcriptionState = state
                }
            }
            self?.accumulatedDuration = response.accumulated_duration ?? 0.0
            self?.lastTriggerReason = response.trigger_reason

            // Always update lines, even if empty - this ensures we clear old lines when appropriate
            self?.transcriptionLines = response.lines
            
            // Always process buffer transcription if we have it
            if let buffer = response.buffer_transcription, !buffer.isEmpty {
                let interimLine = TranscriptionLine(id: UUID().uuidString,
                                                  text: buffer,
                                                  speakerID: nil,
                                                  isInterim: true,
                                                  start: nil,
                                                  end: nil,
                                                  diff: nil)
                self?.transcriptionLines.append(interimLine)
            }
        }
    }
    
    /// Tears down a dead microphone socket and reconnects exactly once.
    /// Debounced by `microphoneReconnectInFlight` so a burst of failures does
    /// not spawn a reconnect storm. Only the microphone source is touched; the
    /// system-audio socket is left intact.
    func recoverMicrophoneWebSocket(reason: String) {
        guard isRecording else { return }
        guard !microphoneReconnectInFlight, microphoneInputRecoveryTask == nil else { return }
        microphoneReconnectAttempt += 1
        if ReconnectBackoffPolicy.shouldGiveUp(afterAttempt: microphoneReconnectAttempt) {
            #if DEBUG
            DevLogger.shared.error("Microphone reconnect exhausted after \(microphoneReconnectAttempt) attempts (\(reason)); giving up", context: "LiveTranscriptionViewModel")
            #endif
            statusMessage = "Microphone audio capture stopped and could not reconnect. Recording may be incomplete."
            enableMicrophone = false
            if !isSystemAudioAvailable || systemAudioWebSocketTask == nil {
                connectionState = .error
                stopRecording()
            }
            return
        }
        microphoneRecoveryGeneration &+= 1
        let recoveryGeneration = microphoneRecoveryGeneration
        microphoneReconnectInFlight = true
        #if DEBUG
        DevLogger.shared.warning("Recovering microphone WebSocket (\(reason)), attempt \(microphoneReconnectAttempt)", context: "LiveTranscriptionViewModel")
        #endif
        microphoneWebSocketRecoveryTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.microphoneRecoveryGeneration == recoveryGeneration {
                    self.microphoneWebSocketRecoveryTask = nil
                    self.microphoneReconnectInFlight = false
                }
            }
            guard self.microphoneRecoveryGeneration == recoveryGeneration,
                  self.isRecording,
                  !Task.isCancelled else { return }
            do {
                try await self.reconnectWebSocket()
                guard self.microphoneRecoveryGeneration == recoveryGeneration,
                      self.isRecording,
                      !Task.isCancelled else { return }
            } catch {
                #if DEBUG
                DevLogger.shared.error("Microphone reconnect failed: \(error)", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
    }

    /// Attempts to reconnect WebSocket after connection failure
    func reconnectWebSocket() async throws {
        #if DEBUG
        DevLogger.shared.info("Attempting to reconnect microphone WebSocket", context: "LiveTranscriptionViewModel")
        #endif
        
        // Cancel the existing task
        microphoneWebSocketTask?.cancel()
        microphoneWebSocketTask = nil
        
        // Update UI state
        await MainActor.run {
            connectionState = .connecting
            statusMessage = "Connection lost, reconnecting..."
        }
        
        // Wait before reconnecting; delay grows with each attempt so a persistent
        // failure spaces out instead of hammering the server.
        let delay = ReconnectBackoffPolicy.delaySeconds(forAttempt: microphoneReconnectAttempt)
        try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        
        // Try to establish a new microphone connection
        try await startListening()
        try Task.checkCancellation()
        try await sendNativeStreamTimingControl(for: .microphone)
        try Task.checkCancellation()
        
        // Update UI on success
        await MainActor.run {
            connectionState = .recording
            statusMessage = "Recording and transcribing..."
            microphoneReconnectAttempt = 0
        }
        
        #if DEBUG
        DevLogger.shared.info("WebSocket reconnection successful", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Fetches transcription settings from backend
    func fetchTranscriptionSettings() async throws {
        let port = APIClient.shared.currentPort
        guard let url = URL(string: "http://localhost:\(port)/settings/transcription") else {
            throw WebSocketError.invalidURL
        }
        
        #if DEBUG
        DevLogger.shared.info("Fetching transcription settings", context: "LiveTranscriptionViewModel")
        #endif
        
        let (data, response) = try await URLSession.shared.data(from: url)
        
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw WebSocketError.invalidResponse
        }
        
        let decoder = JSONDecoder()
        let settingsResponse = try decoder.decode(TranscriptionSettingsResponse.self, from: data)
        self.transcriptionSettings = settingsResponse.settings
        self.postProcessingModel = PostProcessingAutomation.executionModel(
            configuredModelID: settingsResponse.settings.selected_model,
            sessionModel: self.postProcessingModel
        )
        // Seed per-session automation overrides from the saved defaults once per
        // recording so the Transcript Tools card starts from the global config
        // without clobbering any in-session edits on a subsequent re-fetch.
        if !sessionAutomationSeeded {
            sessionAutoRetranscribeOnStop = settingsResponse.settings.auto_retranscribe_on_stop
            sessionAutoRetranscribeDuringRecording = settingsResponse.settings.auto_retranscribe_during_recording
            sessionRetranscribeWindowSeconds = settingsResponse.settings.retranscribe_window_seconds
            sessionAutoAnalyzeOnComplete = settingsResponse.settings.auto_analyze_on_complete
            sessionAutoAnalyzeModes = settingsResponse.settings.auto_analyze_modes
            sessionAutoAnalyzeCustomInstructions = settingsResponse.settings.auto_analyze_custom_instructions
            sessionAutoAnalyzeTiming = settingsResponse.settings.auto_analyze_timing
            sessionAutomationSeeded = true
        }
        
        #if DEBUG
        DevLogger.shared.info("Received transcription settings - model: \(settingsResponse.settings.selected_model), language: \(settingsResponse.settings.language)", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    /// Handles incoming WebSocket messages from microphone source
    @MainActor
    func handleMicrophoneMessage(_ message: URLSessionWebSocketTask.Message) {
        #if DEBUG
        messageLogCounter += 1
        if messageLogCounter % 10 == 1 {
            DevLogger.shared.info("Microphone WebSocket message #\(messageLogCounter)", context: "LiveTranscriptionViewModel")
        }
        #endif
        
        switch message {
        case .string(let text):
            processMicrophoneTranscriptionMessage(text)
        case .data(let data):
            if let text = String(data: data, encoding: .utf8) {
                processMicrophoneTranscriptionMessage(text)
            }
        @unknown default:
            break
        }
    }
    
    /// Handles incoming WebSocket messages from system audio source
    @MainActor
    func handleSystemAudioMessage(_ message: URLSessionWebSocketTask.Message) {
        #if DEBUG
        messageLogCounter += 1
        if messageLogCounter % 10 == 1 {
            DevLogger.shared.info("System Audio WebSocket message #\(messageLogCounter)", context: "LiveTranscriptionViewModel")
        }
        #endif
        
        switch message {
        case .string(let text):
            processSystemAudioTranscriptionMessage(text)
        case .data(let data):
            if let text = String(data: data, encoding: .utf8) {
                processSystemAudioTranscriptionMessage(text)
            }
        @unknown default:
            break
        }
    }
    
    /// Processes transcription messages from microphone
    func processMicrophoneTranscriptionMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let response = try? JSONDecoder().decode(LiveTranscriptionResponse.self, from: data) else {
            return
        }
        
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            
            // Update event-driven state
            if let stateString = response.state,
               let state = TranscriptionState(rawValue: stateString) {
                self.transcriptionState = state
            }
            if let duration = response.accumulated_duration {
                self.accumulatedDuration = duration
            }
            if let trigger = response.trigger_reason {
                self.lastTriggerReason = trigger
            }
            
            // Fold the new tokens into the microphone transcript via the shared
            // merge path (handles new-vs-extend, cross-source line breaks, the
            // global line-break timer, resume-offset stamping, and the combined
            // view rebuild).
            self.appendLiveLines(response.lines, to: .microphone)
        }
    }
    
    /// Processes transcription messages from system audio
    func processSystemAudioTranscriptionMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let response = try? JSONDecoder().decode(LiveTranscriptionResponse.self, from: data) else {
            return
        }
        
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            
            // Fold the new tokens into the system-audio transcript via the shared
            // merge path (handles new-vs-extend, cross-source line breaks, the
            // global line-break timer, resume-offset stamping, and the combined
            // view rebuild).
            self.appendLiveLines(response.lines, to: .systemAudio)
        }
    }
    
    /// Start a global timer that marks all in-progress lines as complete after
    /// 1.5 seconds of silence from ALL sources.
    ///
    /// This is the primary line-grouping knob. It deliberately sits between the
    /// original behavior (closing the sibling source's line on every inbound
    /// batch, which shredded concurrent speech into per-second bubbles) and the
    /// 3s value that let a single source accrete whole paragraphs and blocked
    /// the other source from interleaving. At 1.5s the natural ~1-2s gaps in
    /// conversation close a line so the other source can start a fresh,
    /// interleaved bubble, without returning to per-second fragmentation.
    func startGlobalLineBreakTimer() {
        globalLineBreakTimer = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_500_000_000) // 1.5 seconds
            
            if Task.isCancelled {
                return
            }
            
            // Mark any in-progress lines from BOTH sources as complete
            if !self.microphoneTranscript.isEmpty && !self.microphoneTranscript.last!.lineComplete {
                var lastMicLine = self.microphoneTranscript.removeLast()
                lastMicLine.lineComplete = true
                lastMicLine.text = self.normalizeWhitespace(lastMicLine.text)
                self.microphoneTranscript.append(lastMicLine)
            }
            
            if !self.systemAudioTranscript.isEmpty && !self.systemAudioTranscript.last!.lineComplete {
                var lastSystemLine = self.systemAudioTranscript.removeLast()
                lastSystemLine.lineComplete = true
                lastSystemLine.text = self.normalizeWhitespace(lastSystemLine.text)
                self.systemAudioTranscript.append(lastSystemLine)
            }
            
            self.updateCombinedTranscript()
        }
    }
}

