import Foundation

@available(macOS 14.0, *)
extension LiveTranscriptionViewModel {
    /// Establishes WebSocket connection for system audio from the selected process.
    func startSystemAudioWebSocketConnection(processName: String) async throws {
        try await startSystemAudioWebSocketConnection(sourceName: processName)
    }

    /// Establishes WebSocket connection for system audio from any non-microphone source.
    func startSystemAudioWebSocketConnection(sourceName: String) async throws {
        guard let settings = transcriptionSettings else {
            throw WebSocketError.invalidSettings
        }

        if systemAudioMeetingId == nil {
            systemAudioMeetingId = UUID().uuidString
        }
        if sessionId == nil {
            sessionId = UUID().uuidString
        }

        var components = URLComponents(string: websocketUrl)
        var queryItems = [
            URLQueryItem(name: "model", value: settings.selected_model),
            URLQueryItem(name: "language", value: settings.language),
            URLQueryItem(name: "client", value: "native")
        ]

        if !meetingName.isEmpty {
            queryItems.append(URLQueryItem(name: "meeting_id", value: systemAudioMeetingId))
            queryItems.append(URLQueryItem(name: "meeting_name", value: "\(meetingName) - \(sourceName)"))

            if !meetingPurpose.isEmpty {
                queryItems.append(URLQueryItem(name: "meeting_purpose", value: meetingPurpose))
            }
            if !meetingParticipants.isEmpty {
                queryItems.append(URLQueryItem(name: "meeting_participants", value: meetingParticipants))
            }

            queryItems.append(URLQueryItem(name: "audio_source", value: sourceName))
            if let sessionId {
                queryItems.append(URLQueryItem(name: "session_id", value: sessionId))
            }
            queryItems.append(contentsOf: resumeRecordingQueryItems())

            if systemAudioReconnectInFlight {
                queryItems.append(URLQueryItem(name: "reconnect", value: "true"))
            }
        }

        components?.queryItems = queryItems
        guard let url = components?.url else {
            #if DEBUG
            DevLogger.shared.error("Invalid system audio WebSocket URL: \(websocketUrl)", context: "LiveTranscriptionViewModel")
            #endif
            throw WebSocketError.invalidURL
        }

        #if DEBUG
        DevLogger.shared.info("Connecting system audio WebSocket for \(sourceName) with model: \(settings.selected_model)", context: "LiveTranscriptionViewModel")
        #endif

        let session = URLSession(configuration: .default)
        systemAudioStreamTimingReady = false
        systemAudioWebSocketTask = session.webSocketTask(with: url)
        systemAudioWebSocketTask?.resume()

        #if DEBUG
        DevLogger.shared.info("System audio WebSocket resumed for \(sourceName)", context: "LiveTranscriptionViewModel")
        #endif

        // Wait for the backend's first real message instead of an arbitrary
        // fixed sleep. The prior unconditional 500ms sleep here added a flat
        // delay to every recording start regardless of how quickly the
        // socket was actually ready, and it never verified the connection
        // actually succeeded. This mirrors the readiness wait already used
        // for the microphone socket in startListening().
        var receivedFirstMessage = false
        systemAudioConnectionError = nil
        systemAudioWebSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success(let message):
                Task { @MainActor in
                    self.handleSystemAudioMessage(message)
                    if !receivedFirstMessage {
                        receivedFirstMessage = true
                        #if DEBUG
                        DevLogger.shared.info("First system audio WebSocket message received for \(sourceName), connection successful", context: "LiveTranscriptionViewModel")
                        #endif
                        self.systemAudioConnectionTask?.cancel()
                    }
                    self.receiveSystemAudioMessages() // Continue receiving messages
                }

            case .failure(let error):
                Task { @MainActor [weak self] in
                    self?.systemAudioConnectionError = error
                    self?.systemAudioConnectionTask?.cancel()
                }
            }
        }

        systemAudioConnectionTask = Task {
            do {
                // Same 30s ceiling as the microphone path: local models can take
                // 15-20s to load, but this resolves almost immediately for
                // API-backed models since the backend's first status message
                // does not wait on real audio content (it's emitted from the
                // results formatter's very first pass over empty state).
                try await Task.sleep(nanoseconds: 30_000_000_000)
                throw NSError(domain: "com.basil.websocket", code: -1, userInfo: [NSLocalizedDescriptionKey: "System audio WebSocket connection timeout"])
            } catch is CancellationError {
                if let error = self.systemAudioConnectionError {
                    throw error
                }
                #if DEBUG
                DevLogger.shared.info("System audio WebSocket connection established for \(sourceName)", context: "LiveTranscriptionViewModel")
                #endif
            }
        }

        try await systemAudioConnectionTask?.value
    }

    /// Tears down a dead system-audio socket and reconnects with backoff.
    func recoverSystemAudioWebSocket(reason: String) {
        guard isRecording, !systemAudioReconnectInFlight else { return }
        systemAudioReconnectAttempt += 1
        if ReconnectBackoffPolicy.shouldGiveUp(afterAttempt: systemAudioReconnectAttempt) {
            #if DEBUG
            DevLogger.shared.error("System audio reconnect exhausted after \(systemAudioReconnectAttempt) attempts (\(reason)); giving up", context: "LiveTranscriptionViewModel")
            #endif
            statusMessage = "System audio capture stopped and could not reconnect. Recording may be incomplete."
            if microphoneWebSocketTask == nil {
                connectionState = .error
                stopRecording()
            }
            return
        }
        systemAudioReconnectInFlight = true
        #if DEBUG
        DevLogger.shared.warning("Recovering system audio WebSocket (\(reason)), attempt \(systemAudioReconnectAttempt)", context: "LiveTranscriptionViewModel")
        #endif

        systemAudioWebSocketTask?.cancel()
        systemAudioWebSocketTask = nil
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.systemAudioReconnectInFlight = false }
            guard self.isRecording else { return }
            do {
                try await self.reconnectSystemAudioWebSocket()
                self.systemAudioReconnectAttempt = 0
            } catch {
                #if DEBUG
                DevLogger.shared.error("System audio reconnect failed: \(error)", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
    }

    /// Attempts to reconnect the system audio WebSocket if disconnected.
    func reconnectSystemAudioWebSocket() async throws {
        #if DEBUG
        DevLogger.shared.warning("Attempting to reconnect system audio WebSocket", context: "LiveTranscriptionViewModel")
        #endif

        systemAudioWebSocketTask?.cancel()
        systemAudioWebSocketTask = nil

        // Wait before reconnecting; delay grows with each attempt. This path
        // previously retried without any delay.
        let delay = ReconnectBackoffPolicy.delaySeconds(forAttempt: systemAudioReconnectAttempt)
        try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))

        if systemAudioCaptureMode == .globalOutput {
            try await startSystemAudioWebSocketConnection(sourceName: "System Audio")
        } else if let processTap = systemAudioState?.processTap {
            try await startSystemAudioWebSocketConnection(processName: processTap.process.name)
        } else {
            throw AudioError.engineSetupFailed
        }
        try await sendNativeStreamTimingControl(for: .systemAudio)
    }
}
