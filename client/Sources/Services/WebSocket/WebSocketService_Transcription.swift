// WIP: Modularization of transcription logic. sendAudioDataWithContext, setAudioChunkInfo, scheduleModelUnload, and cancelModelUnload are present for now.
import Foundation

final class WebSocketService_Transcription {
    unowned let parent: WebSocketService

    init(parent: WebSocketService) {
        self.parent = parent
    }

    @MainActor
    func setAudioChunkInfo(chunkId: String, source: String, applicationName: String? = nil) {
        parent.audioChunks[chunkId] = source
        parent.audioChunkApplications[chunkId] = applicationName
        parent.audioChunkTimestamps[chunkId] = Date()
        parent.cleanupOldChunks()
    }

    @MainActor
    func sendAudioDataWithContext(
        _ data: Data,
        appName: String?,
        windowTitle: String?,
        taskCategory: String?,
        flowContext: String? = nil,
        forMeeting: Bool = false,
        clarificationContext: [String: Any]? = nil
    ) {
        // Legacy meeting-specific handling removed; all audio uses standard WebSocket
        
        // Below is the standard transcription flow
        guard let webSocket = parent.webSocket, parent.isConnected else {
            parent.eventSubject.send(.transcriptionFailed("Not connected to server"))
            return
        }
        
        // Generate a chunk ID for tracking
        let chunkId = UUID().uuidString
        
        // First send context information as JSON
        var contextInfo: [String: Any] = [
            "type": "context_info",
            "app_name": appName ?? "",
            "window_title": windowTitle ?? "",
            "task_category": taskCategory ?? "",
            "chunk_id": chunkId  // Include the chunk ID in context info
        ]
        if let flowContext = flowContext {
            contextInfo["flowContext"] = flowContext
        }
        
        // Add clarification context if it exists
        if let clarificationContext = clarificationContext {
            contextInfo["clarification_context"] = clarificationContext
        }
        
        // Also register this chunk ID for tracking
        setAudioChunkInfo(
            chunkId: chunkId, 
            source: "local_mic",
            applicationName: appName
        )
        
        do {
            let jsonData = try JSONSerialization.data(withJSONObject: contextInfo)
            if let jsonString = String(data: jsonData, encoding: .utf8) {
                #if DEBUG
                DevLogger.shared.info("Sending context info with chunk_id \(chunkId): \(jsonString)", context: "websocket")
                #endif
                
                webSocket.send(.string(jsonString)) { error in
                    if let error = error {
                        #if DEBUG
                        DevLogger.shared.error("Failed to send context info: \(error)", context: "websocket")
                        #endif
                    }
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to serialize context info: \(error)", context: "websocket")
            #endif
        }
        
        // Then send the audio data
        webSocket.send(.data(data)) { [weak parent] error in
            if let error = error {
                Task { @MainActor in
                    parent?.eventSubject.send(.transcriptionFailed(error.localizedDescription))
                }
            }
        }
    }

    @MainActor
    func scheduleModelUnload(delaySeconds: Int) async throws {
        guard parent.isConnected else {
            print("Cannot schedule model unload: WebSocket not connected")
            throw WebSocketService.WebSocketError.notConnected
        }
        print("\n⏲️ Scheduling model unload after \(delaySeconds) seconds")
        let modelUnloadAction: [String: Any] = [
            "agent_task_action": "schedule_model_unload",
            "delay_seconds": delaySeconds
        ]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: modelUnloadAction),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            print("❌ Failed to create JSON model unload action")
            throw WebSocketService.WebSocketError.invalidState
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            parent.webSocket?.send(.string(jsonString)) { error in
                if let error = error {
                    print("❌ Failed to send model unload action: \(error)")
                    continuation.resume(throwing: error)
                } else {
                    print("✅ Successfully sent model unload action")
                    continuation.resume()
                }
            }
        }
    }

    @MainActor
    func cancelModelUnload() async throws {
        guard parent.isConnected else {
            print("Cannot cancel model unload: WebSocket not connected")
            throw WebSocketService.WebSocketError.notConnected
        }
        print("\n🚫 Cancelling scheduled model unload")
        let modelUnloadAction = ["agent_task_action": "cancel_model_unload"]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: modelUnloadAction),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            print("❌ Failed to create JSON model unload action")
            throw WebSocketService.WebSocketError.invalidState
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            parent.webSocket?.send(.string(jsonString)) { error in
                if let error = error {
                    print("❌ Failed to send cancel unload action: \(error)")
                    continuation.resume(throwing: error)
                } else {
                    print("✅ Successfully sent cancel unload action")
                    continuation.resume()
                }
            }
        }
    }

    @MainActor
    func initializeTranscription() async throws {
        guard parent.isConnected, let webSocket = parent.webSocket else {
            print("Cannot initialize transcription: WebSocket not connected")
            parent.eventSubject.send(.transcriptionFailed("Not connected to server"))
            throw WebSocketService.WebSocketError.notConnected
        }
        print("\n🎯 Sending transcription initialization request")
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            webSocket.send(.string("init_transcription")) { error in
                if let error = error {
                    print("❌ Failed to send transcription initialization: \(error)")
                    continuation.resume(throwing: error)
                } else {
                    print("✅ Successfully sent transcription initialization request")
                    continuation.resume()
                }
            }
        }
    }

    @MainActor
    func sendAudioData(_ data: Data, forMeeting: Bool = false) {
        guard parent.isConnected, let webSocket = parent.webSocket else {
            #if DEBUG
            DevLogger.shared.error("Not connected to regular WebSocket - cannot send audio data", context: "websocket")
            #endif
            parent.eventSubject.send(.transcriptionFailed("Not connected to server"))
            return
        }
        #if DEBUG
        DevLogger.shared.info("Sending \(data.count) bytes of audio data through REGULAR WebSocket", context: "websocket")
        #endif
        webSocket.send(.data(data)) { [weak parent] error in
            if let error = error {
                #if DEBUG
                DevLogger.shared.error("Failed to send regular audio data: \(error)", context: "websocket")
                #endif
                Task { @MainActor [weak parent] in
                    parent?.eventSubject.send(.transcriptionFailed(error.localizedDescription))
                }
            } else {
                #if DEBUG
                DevLogger.shared.info("Successfully sent \(data.count) bytes of regular audio data", context: "websocket")
                #endif
            }
        }
    }

    @MainActor
    func cleanupOldChunks() {
        let cutoffTime = Date().addingTimeInterval(-300) // 5 minutes ago
        let oldChunkIds = parent.audioChunkTimestamps.filter { $0.value < cutoffTime }.keys
        for chunkId in oldChunkIds {
            parent.audioChunks.removeValue(forKey: chunkId)
            parent.audioChunkApplications.removeValue(forKey: chunkId)
            parent.audioChunkTimestamps.removeValue(forKey: chunkId)
        }
        if !oldChunkIds.isEmpty {
            #if DEBUG
            DevLogger.shared.info("Removed \(oldChunkIds.count) expired audio chunks from tracking", context: "WebSocket")
            #endif
        }
    }

    @MainActor
    func setCurrentAudioSource(_ source: String) {
        parent.currentAudioSource = source
    }

    @MainActor
    func setCurrentApplicationName(_ name: String?) {
        parent.currentApplicationName = name
        #if DEBUG
        if let name = name {
            DevLogger.shared.info("Set current application name to: \(name)", context: "websocket")
        } else {
            DevLogger.shared.info("Cleared current application name", context: "websocket")
        }
        #endif
    }

    @MainActor
    func receiveTranscriptionMessages() {
        parent.webSocket?.receive { [weak parent] result in
            guard let parent = parent else { return }
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    if let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let event = json["event"] as? String {
                        switch event {
                        case "transcription_started":
                            #if DEBUG
                            DevLogger.shared.info("[Transcription] Broadcasting transcription_started event", context: "websocket")
                            #endif
                            Task { @MainActor in
                                parent.eventSubject.send(.transcriptionStarted)
                            }
                        case "transcription_completed":
                            Task { @MainActor in
                                parent.transcription.handleTranscriptionCompleted(json: json)
                            }
                        default:
                            break // Ignore other events for now
                        }
                    }
                default:
                    break // Ignore non-string messages for now
                }
                // Continue receiving messages
                Task { @MainActor in
                    parent.transcription.receiveTranscriptionMessages()
                }
            case .failure(let error):
                #if DEBUG
                DevLogger.shared.error("[Transcription] WebSocket receive error: \(error)", context: "websocket")
                #endif
                // Optionally handle reconnection or error state here
            }
        }
    }

    @MainActor
    func handleTranscriptionCompleted(json: [String: Any]) {
        if let flowContext = json["flowContext"] as? String {
            #if DEBUG
            DevLogger.shared.info("Broadcasting flowContextTranscriptionCompleted event for context: \(flowContext)", context: "websocket")
            #endif
            parent.eventSubject.send(.flowContextTranscriptionCompleted(json))
        } else if let transcribedText = json["data"] as? String {
            #if DEBUG
            DevLogger.shared.info("Broadcasting transcription_completed event with text", context: "websocket")
            #endif
            parent.transcribedText = transcribedText
            let chunkId = json["chunk_id"] as? String
            var audioSource: String
            var applicationName: String?
            let segmentId = UUID().uuidString
            if let chunkId = chunkId, let source = parent.audioChunks[chunkId] {
                audioSource = source
                applicationName = parent.audioChunkApplications[chunkId] as? String
                #if DEBUG
                DevLogger.shared.info("Found matching chunk ID \(chunkId) with source: \(source)", context: "websocket")
                #endif
                parent.audioChunks.removeValue(forKey: chunkId)
                parent.audioChunkApplications.removeValue(forKey: chunkId)
                parent.audioChunkTimestamps.removeValue(forKey: chunkId)
            } else {
                audioSource = parent.currentAudioSource ?? "local_mic"
                applicationName = parent.currentApplicationName
                #if DEBUG
                if chunkId != nil {
                    DevLogger.shared.warning("Chunk ID \(chunkId!) received but not found in tracking. Using fallback source: \(audioSource)", context: "websocket")
                } else {
                    DevLogger.shared.info("No chunk ID in response. Using current source: \(audioSource)", context: "websocket")
                }
                #endif
            }
            var enrichedData: [String: Any] = [
                "text": transcribedText,
                "audio_source": audioSource,
                "segment_id": segmentId,
                "timestamp": Date().timeIntervalSince1970
            ]
            if audioSource == "system_audio" && applicationName != nil {
                enrichedData["application_name"] = applicationName
            }
            parent.eventSubject.send(.transcriptionCompleted(transcribedText))
            #if DEBUG
            DevLogger.shared.info("Sent enriched transcript data with audio_source: \(audioSource)\(applicationName != nil ? ", application: \(applicationName!)" : "")", context: "websocket")
            #endif
        }
    }

    @MainActor
    func handleTranscriptionFailedEvent(json: [String: Any]) {
        if let error = json["data"] as? String {
            #if DEBUG
            DevLogger.shared.error("Broadcasting transcription_failed event: \(error)", context: "websocket")
            #endif
            Task { @MainActor in
                parent.eventSubject.send(.transcriptionFailed(error))
            }
        }
    }

    @MainActor
    func handleTranscriptionModelReadyEvent(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Broadcasting model_ready event", context: "websocket")
        #endif
        Task { @MainActor in
            parent.eventSubject.send(.modelReady)
        }
    }

    @MainActor
    func handleFlowContextTranscriptionCompleted(json: [String: Any]) {
        if let data = json["data"] as? [String: Any] {
            #if DEBUG
            DevLogger.shared.info("Broadcasting flow_context_transcription_completed event with data", context: "websocket")
            #endif
            Task { @MainActor in
                parent.eventSubject.send(.flowContextTranscriptionCompleted(data))
            }
        }
    }

    @MainActor
    func handleWebSocketMessage(_ json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("📥 WEBSOCKET MESSAGE RECEIVED: \(json)", context: "websocket")
        #endif
        
        if let event = json["event"] as? String {
            #if DEBUG
            DevLogger.shared.info("Handling transcription event: \(event)", context: "websocket")
            #endif
            
            switch event {
            case "transcription_started":
                #if DEBUG
                DevLogger.shared.info("[Transcription] Broadcasting transcription_started event", context: "websocket")
                #endif
                parent.eventSubject.send(.transcriptionStarted)

            case "transcription_progress":
                let payload = json["data"] as? [String: Any] ?? json
                parent.eventSubject.send(.transcriptionProgress(payload))
                
            case "transcription_completed":
                #if DEBUG
                DevLogger.shared.info("[Transcription] Broadcasting transcription_completed event", context: "websocket")
                #endif
                handleTranscriptionCompleted(json: json)
                
            case "transcription_failed":
                handleTranscriptionFailedEvent(json: json)
                
            case "transcription_model_ready":
                handleTranscriptionModelReadyEvent(json: json)
                
            case "flow_context_transcription_completed":
                handleFlowContextTranscriptionCompleted(json: json)
                
            default:
                #if DEBUG
                DevLogger.shared.warning("Unhandled transcription event: \(event)", context: "websocket")
                #endif
                break
            }
        } else {
            #if DEBUG
            DevLogger.shared.warning("Unhandled or unknown WebSocket JSON message: \(json)", context: "websocket")
            #endif
        }
    }

}
