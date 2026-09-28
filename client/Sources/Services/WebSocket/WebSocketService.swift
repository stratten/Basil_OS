import Foundation
import Combine
import AppKit

enum WebSocketEvent {
    case transcriptionStarted
    case transcriptionProgress([String: Any])
    case transcriptionCompleted(String)
    case transcriptionFailed(String)
    case connectionStateChanged(Bool)
    case modelReady
    case conversationEvent([String: Any])
    case transcriptionCanceled
    case flowContextTranscriptionCompleted([String: Any])
    case agentTaskStarted
    case agentTaskProgress([String: Any])
    case agentTaskResult([String: Any])
    // New streaming agentTask events for intelligent capture termination
    case agentTaskWordDetected([String: Any])
    case agentTaskSilenceProgress([String: Any])
    case agentTaskCaptureComplete([String: Any])
    // New workflow and step progress events for live todo checklist
    case workflowPlanReady([String: Any])
    case stepProgressUpdate([String: Any])
    // Dynamic agent step reporting events
    case dynamicStepAdded([String: Any])
    case dynamicStepUpdated([String: Any])
    case agentProgressUpdate([String: Any])
    // Collaborative workflow and checkpoint events (Phase 3)
    case collaborativeCheckpointRequest([String: Any])
    case checkpointWaiting([String: Any])
    case checkpointResumed([String: Any])
    case sessionContextInfo([String: Any])
    // Execution approval events
    case executionApprovalRequest([String: Any])

    // Live "type at cursor" dictation events. Emitted by the dedicated
}

// Separate enum for conversation-specific events to avoid impacting other parts of the app
enum ConversationEventType: String {
    case message = "conversation_message"
    case token = "conversation_token"
    case error = "conversation_error"
}

@MainActor
final class WebSocketService: NSObject, URLSessionWebSocketDelegate {
    // MARK: - Properties
    static let shared = WebSocketService()
    
    // Make WebSocketError a nested type within WebSocketService
    enum WebSocketError: Error {
        case notConnected
        case initializationTimeout
        case connectionTimeout
        case invalidState
    }
    
    // Token log sampling counter (log every 20th token)
    private var tokenLogCounter = 0
    
    var webSocket: URLSessionWebSocketTask?
    var session: URLSession!
    var isReconnecting = false
    var reconnectTask: Task<Void, Never>?
    var pingTimer: Timer?
    var reconnectAttempt = 0
    var cancellables = Set<AnyCancellable>()
    let eventSubject = PassthroughSubject<WebSocketEvent, Never>()
    
    @Published var isConnected = false
    @Published var transcriptionStatus: String = ""
    @Published var transcribedText: String = ""
    
    // Current audio source for transcription
    var currentAudioSource: String?
    var currentApplicationName: String?
    
    // Chunk-based audio source tracking
    var audioChunks: [String: String] = [:] // [chunkId: audioSource]
    var audioChunkApplications: [String: String?] = [:] // [chunkId: applicationName]
    var audioChunkTimestamps: [String: Date] = [:] // [chunkId: timestamp]
    
    // Closure callback for WebSocket close events
    var onClose: (() -> Void)?
    

    
    // Use dynamic API base URL based on current backend port
    var apiBaseURL: String {
        "ws://localhost:\(APIClient.shared.currentPort)"
    }

    nonisolated private static let sensitiveWebSocketKeys: Set<String> = [
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "authorization",
        "api_key",
        "client_secret",
        "secret",
        "password"
    ]

    nonisolated private static func isSensitiveWebSocketPayload(_ text: String) -> Bool {
        let lowercased = text.lowercased()
        if lowercased.contains("gho_") {
            return true
        }
        return sensitiveWebSocketKeys.contains { lowercased.contains($0) }
    }

    nonisolated private static func safeWebSocketLogSummary(for text: String) -> String {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "text_length=\(text.count)"
        }

        let safeFields = ["agent_task_action", "type", "event_type", "request_id", "correlation_id", "agent_task_id"]
            .compactMap { key -> String? in
                guard let value = json[key] else { return nil }
                return "\(key)=\(value)"
            }
        let redactedKeys = json.keys
            .filter { sensitiveWebSocketKeys.contains($0.lowercased()) }
            .sorted()
        let visibleKeys = json.keys
            .filter { !sensitiveWebSocketKeys.contains($0.lowercased()) }
            .sorted()

        return "json \(safeFields.joined(separator: " ")) keys=\(visibleKeys) redacted_keys=\(redactedKeys)"
    }

    nonisolated private static func safeReceiveResultSummary(_ result: Result<URLSessionWebSocketTask.Message, Error>) -> String {
        switch result {
        case .success(let message):
            switch message {
            case .string(let text):
                if isSensitiveWebSocketPayload(text) {
                    return "success(string: \(safeWebSocketLogSummary(for: text)))"
                }
                return "success(string_length=\(text.count))"
            case .data(let data):
                return "success(data_length=\(data.count))"
            @unknown default:
                return "success(unknown_message)"
            }
        case .failure(let error):
            return "failure(\(error))"
        }
    }
    
    // Add transcription module for modularized methods
    @MainActor lazy var transcription = WebSocketService_Transcription(parent: self)
    // Add conversation module for modularized conversation methods
    @MainActor lazy var conversation = WebSocketService_Conversation(parent: self)
    // Add agentTask module for modularized agentTask methods
    @MainActor lazy var agentTask = WebSocketService_AgentTask(parent: self)
    
    var modelIsReady: Bool = false
    
    override init() {
        super.init()
        // Reset modelIsReady on startup
        modelIsReady = false
    }
    
    func receiveMessage() {
        webSocket?.receive { [weak self] result in
            #if DEBUG
            DevLogger.shared.info("WebSocket receive result: \(Self.safeReceiveResultSummary(result))", context: "websocket")
            #endif

            // Immediately arm the next receive before processing the current result
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                
                // Arm the next receive first, now safely on the MainActor
                self.receiveMessage()
                
                switch result {
                case .success(let message):
                    switch message {
                            case .string(let text):
                        
                        if let data = text.data(using: .utf8),
                           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                            
                            // Sample logging for conversation tokens (every 20th or important events)
                            let isConversationToken = (json["event_type"] as? String) == "conversation_token"
                            let isFinal = (json["is_final"] as? Bool) == true
                            let chunkId = json["chunk_id"] as? Int ?? 0
                            
                            let shouldLog = !isConversationToken || (chunkId % 20 == 0) || isFinal || chunkId == 0
                            
                            #if DEBUG
                            if shouldLog {
                                DevLogger.shared.info("WebSocket .success summary: \(Self.safeWebSocketLogSummary(for: text))", context: "websocket")
                                
                                // Raw-level token log for diagnostics
                                if isConversationToken, let cid = json["chunk_id"], let mid = json["message_id"] {
                                    DevLogger.shared.info("[WS RAW] chunk_id=\(cid) for message_id=\(mid)", context: "websocket")
                                }
                            }
                            #endif
                            // Canary message handler
                            if let eventType = json["event_type"] as? String, eventType == "canary" {
                                #if DEBUG
                                DevLogger.shared.info("Received CANARY WebSocket message: \(json)", context: "websocket")
                                #endif
                            }
                                // Route messages to the appropriate handler based on event_type
                                if let eventType = json["event_type"] as? String {
                                    #if DEBUG
                                    DevLogger.shared.info("[WS ROUTER] event_type='\(eventType)'", context: "websocket")
                                    #endif

                                
                                switch eventType {
                                case "history_chat_event", "conversation_token", "conversation_message", "conversation_error", "conversation_toggled":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing conversation event_type '\(eventType)' to conversation handler", context: "websocket")
                                    #endif
                                    self.conversation.handleWebSocketMessage(json)
                                    
                                case "agent_task_capture_started":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask start handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskStarted(json: json)

                                case "agent_task_progress":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask progress handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskProgress(json: json)

                                case "agent_task_result":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask result handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskResult(json: json)

                                case "agent_task_word_detected":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask word handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskWordDetected(json: json)

                                case "agent_task_silence_progress":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask silence handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskSilenceProgress(json: json)

                                case "agent_task_capture_complete":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask capture-complete handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskCaptureComplete(json: json)

                                case "agent_task_streaming":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask streaming handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskStreaming(json: json)

                                case "agent_task_streaming_complete":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agent_task event_type '\(eventType)' to agentTask streaming-complete handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleAgentTaskStreamingComplete(json: json)

                                case "agentTask_progress", "agentTask_result", "capture_request", "agentTask_capture_started", "agentTask_word_detected", "agentTask_silence_progress", "agentTask_capture_complete", "agentTask_streaming", "agentTask_streaming_complete", "workflow_plan_ready", "step_progress_update", "dynamic_step_added", "dynamic_step_updated", "agent_progress_update", "collaborative_checkpoint_request", "checkpoint_waiting", "checkpoint_resumed", "session_context_info", "execution_approval_request":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agentTask event_type '\(eventType)' to agentTask handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleWebSocketMessage(json)

                                case "scheduled_agent_task_run_started", "scheduled_agent_task_run_completed", "scheduled_agent_task_missed":
                                    // The mini panel WKWebView talks to the WS directly for row
                                    // updates, but Swift needs to hear ``run_started`` to bring
                                    // the host NSPanel forward (it might not be visible yet at
                                    // the moment the first event fires). NotificationCenter is
                                    // the lightest-weight way to fan this out without coupling
                                    // WebSocketService to AppDelegate.
                                    #if DEBUG
                                    DevLogger.shared.info("Posting scheduled-agent-task notification for event_type '\(eventType)'", context: "websocket")
                                    #endif
                                    NotificationCenter.default.post(
                                        name: NSNotification.Name("BasilScheduledAgentTaskWSEvent"),
                                        object: nil,
                                        userInfo: json
                                    )

                                case "ambient_suggestion_created", "ambient_suggestion_updated", "ambient_suggestion_status_changed":
                                    NotificationCenter.default.post(
                                        name: NSNotification.Name("BasilAmbientSuggestionWSEvent"),
                                        object: nil,
                                        userInfo: json
                                    )

                                case "appearance_updated":
                                    self.handleAppearanceUpdated(json)

                                case "audio_activity_probe":
                                    // Mechanical meeting-detection probe: report which
                                    // monitored apps are producing audio (no audio tap).
                                    #if DEBUG
                                    DevLogger.shared.info("Handling audio_activity_probe", context: "websocket")
                                    #endif
                                    self.handleAudioActivityProbe(json)

                                case "meeting_calendar_probe":
                                    // Calendar-only meeting detection probe: report joinable
                                    // calendar events without touching audio or Activity Capture.
                                    #if DEBUG
                                    DevLogger.shared.info("Handling meeting_calendar_probe", context: "websocket")
                                    #endif
                                    self.handleMeetingCalendarProbe(json)

                                case "meeting_detected", "meeting_ended", "meeting_prompt_expired":
                                    // The mechanical meeting-detection loop surfaces its
                                    // own minimal panel. Like the scheduled-agent-task
                                    // events, fan this out via NotificationCenter so the
                                    // AppDelegate can lazily build/show the panel without
                                    // coupling WebSocketService to it.
                                    #if DEBUG
                                    DevLogger.shared.info("Posting meeting-detection notification for event_type '\(eventType)'", context: "websocket")
                                    #endif
                                    NotificationCenter.default.post(
                                        name: NSNotification.Name("BasilMeetingDetectedWSEvent"),
                                        object: nil,
                                        userInfo: json
                                    )
                                
                                case "auth_token_request":
                                    // Backend is requesting the auth token for LLM calls
                                    #if DEBUG
                                    DevLogger.shared.info("🔐 Backend requesting auth token", context: "websocket")
                                    #endif
                                    self.handleAuthTokenRequest(json)
                                
                                case "agent_task_step_detail", "conversation_agent_status":
                                    #if DEBUG
                                    DevLogger.shared.info(
                                        "Ignoring browser-owned WebSocket event_type '\(eventType)' in native router",
                                        context: "websocket"
                                    )
                                    #endif

                                default:
                                    // For unknown event_type messages, send to both transcription and generic handlers
                                    self.transcription.handleWebSocketMessage(json)
                                    WebSocketService_GenericHandlers.handleWebSocketMessage(json)
                                }
                            } else if let messageType = json["type"] as? String {
                                // Handle messages with "type" field (legacy format)
                                switch messageType {
                                case "agentTask_started":
                                    #if DEBUG
                                    DevLogger.shared.info("Routing agentTask type '\(messageType)' to agentTask handler", context: "websocket")
                                    #endif
                                    self.agentTask.handleWebSocketMessage(json)
                                    
                                case "operation_state_query":
                                    #if DEBUG
                                    DevLogger.shared.info("Handling operation state query from backend (type field)", context: "websocket")
                                    #endif
                                    self.handleOperationStateQuery(json)
                                    
                                case "widget_state_query":
                                    #if DEBUG
                                    DevLogger.shared.info("Handling widget state query from backend (type field)", context: "websocket")
                                    #endif
                                    self.handleWidgetStateQuery(json)

                                case "mcp_token_store":
                                    WebSocketService_MCP.handleTokenStore(json)

                                case "mcp_token_request":
                                    WebSocketService_MCP.handleTokenRequest(json, parent: self)

                                case "mcp_token_delete":
                                    WebSocketService_MCP.handleTokenDelete(json)

                                default:
                                    // For unknown type messages, send to both transcription and generic handlers
                                    self.transcription.handleWebSocketMessage(json)
                                    WebSocketService_GenericHandlers.handleWebSocketMessage(json)
                                }
                            } else {
                                // For messages without event_type or type, send to both transcription and generic handlers
                                self.transcription.handleWebSocketMessage(json)
                                WebSocketService_GenericHandlers.handleWebSocketMessage(json)
                            }
                        } else {
                            // Always log JSON parsing errors to the system logs
                            DevLogger.shared.error("[WebSocket] ERROR: Failed to parse WebSocket message as JSON: \(text)", context: "websocket")
                            #if DEBUG
                            DevLogger.shared.error("Failed to parse WebSocket message as JSON: \(text)", context: "websocket")
                            #endif
                        }
                    case .data(let data):
                        #if DEBUG
                        DevLogger.shared.info("WebSocket .success with binary data: \(data.count) bytes", context: "websocket")
                        #endif
                        WebSocketService_GenericHandlers.handleWebSocketData(data)
                    @unknown default:
                        #if DEBUG
                        DevLogger.shared.warning("WebSocket .success with unknown message type", context: "websocket")
                        #endif
                        WebSocketService_GenericHandlers.handleUnknownWebSocketMessageType()
                    }
                case .failure(let error):
                    #if DEBUG
                    DevLogger.shared.error("WebSocket .failure with error: \(error)", context: "websocket")
                    #endif
                    WebSocketService_GenericHandlers.handleWebSocketError(error, parent: self)
                }
            }
        }
    }
    
    func disconnect() {
        // Only disconnect if explicitly requested (e.g., widget closing)
        print("Explicit disconnect requested")
        stopPingTimer()
        
        // Close the main WebSocket connection
        if let webSocket = webSocket {
            webSocket.cancel(with: .normalClosure, reason: nil)
            self.webSocket = nil
        }
        
        session?.invalidateAndCancel()
        session = nil
        isConnected = false
        isReconnecting = false
        reconnectAttempt = 0
        reconnectTask?.cancel()
        reconnectTask = nil
    }
    
    func sendMessage(_ message: String, forMeeting: Bool = false) {
        // Send all messages on the main WebSocket
        guard isConnected, let webSocket = webSocket else {
            print("Cannot send message: WebSocket not connected")
            return
        }
        webSocket.send(.string(message)) { error in
            if let error = error {
                print("Failed to send message: \(error)")
            }
        }
    }
    
    /// Handle auth token request from backend
    /// Backend needs the token to make LLM calls through the auth proxy
    @MainActor
    private func handleAuthTokenRequest(_ json: [String: Any]) {
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("🔐 Auth token request missing request_id", context: "websocket")
            #endif
            return
        }
        
        // Get token from AuthService
        let token = AuthService.shared.getAccessToken()
        
        // Build response
        var response: [String: Any] = [
            "type": "auth_token_response",
            "request_id": requestId
        ]
        
        if let token = token {
            response["access_token"] = token
            #if DEBUG
            DevLogger.shared.info("🔐 Sending auth token to backend for request \(requestId)", context: "websocket")
            #endif
        } else {
            response["access_token"] = NSNull()
            #if DEBUG
            DevLogger.shared.warning("🔐 No auth token available for request \(requestId)", context: "websocket")
            #endif
        }
        
        // Send response back to backend
        if let jsonData = try? JSONSerialization.data(withJSONObject: response),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            sendMessage(jsonString)
        }
    }
    
    @MainActor
    func sendAudioData(_ data: Data, forMeeting: Bool = false) {
        transcription.sendAudioData(data, forMeeting: forMeeting)
    }
    
    // Remove the original setAudioChunkInfo method
    // Add a forwarding method to the modularized implementation
    @MainActor
    func setAudioChunkInfo(chunkId: String, source: String, applicationName: String? = nil) {
        transcription.setAudioChunkInfo(chunkId: chunkId, source: source, applicationName: applicationName)
    }
    
    @MainActor
    func cleanupOldChunks() {
        transcription.cleanupOldChunks()
    }
    
    @MainActor
    func setCurrentAudioSource(_ source: String) {
        transcription.setCurrentAudioSource(source)
    }
    
    @MainActor
    func setCurrentApplicationName(_ name: String?) {
        transcription.setCurrentApplicationName(name)
    }
    
    @MainActor
    func initializeTranscription() async throws {
        try await transcription.initializeTranscription()
    }
    
    @MainActor
    func scheduleModelUnload(delaySeconds: Int) async throws {
        try await transcription.scheduleModelUnload(delaySeconds: delaySeconds)
    }

    @MainActor
    func cancelModelUnload() async throws {
        try await transcription.cancelModelUnload()
    }
    
    @MainActor
    func sendAgentTaskCancellation(agentTaskId: String? = nil) async throws {
        guard isConnected, let webSocket = webSocket else {
            throw WebSocketError.notConnected
        }
        
        var cancellationMessage: [String: String] = [
            "agent_task_action": "cancel_agent_task",
            "reason": "user_cancelled"
        ]
        if let agentTaskId, !agentTaskId.isEmpty {
            cancellationMessage["agent_task_id"] = agentTaskId
        }
        
        guard let jsonData = try? JSONSerialization.data(withJSONObject: cancellationMessage),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            throw WebSocketError.invalidState
        }
        
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            webSocket.send(.string(jsonString)) { error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }
    
    // Basic cleanup that can be safely called from any context
    nonisolated func performBasicCleanup() {
        // Since we can't access actor-isolated properties directly,
        // we need to capture them on the main actor first
        Task { @MainActor in
            // Capture and cancel WebSocket
            if let ws = webSocket {
                ws.cancel(with: .normalClosure, reason: nil)
            }
            
            // Clear properties
            webSocket = nil
            isConnected = false
            isReconnecting = false
        }
    }
    
    deinit {
        // Since we can't use async/await in deinit and we're potentially
        // crossing actor boundaries, we'll just do basic cleanup
        performBasicCleanup()
    }
    
    @MainActor
    func sendAudioDataWithContext(
        _ data: Data,
        appName: String?,
        windowTitle: String?,
        taskCategory: String?,
        flowContext: String? = nil,
        forMeeting: Bool = false
    ) {
        transcription.sendAudioDataWithContext(
            data,
            appName: appName,
            windowTitle: windowTitle,
            taskCategory: taskCategory,
            flowContext: flowContext,
            forMeeting: forMeeting
        )
    }
    
    @MainActor
    private func handleOperationStateQuery(_ json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Processing operation state query from backend", context: "websocket")
        #endif
        
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("Operation state query missing request_id", context: "websocket")
            #endif
            return
        }
        
        // Check current operation state
        let canAcceptAgentTask = checkCanAcceptAgentTask()
        
        // Send response back to backend
        let response = [
            "type": "operation_state_response",
            "request_id": requestId,
            "can_accept_agent_task": canAcceptAgentTask,
            "timestamp": Date().timeIntervalSince1970
        ] as [String: Any]
        
        if let responseData = try? JSONSerialization.data(withJSONObject: response),
           let responseString = String(data: responseData, encoding: .utf8) {
            sendMessage(responseString)
            #if DEBUG
            DevLogger.shared.info("Sent operation state response: \(response)", context: "websocket")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to serialize operation state response", context: "websocket")
            #endif
        }
    }
    
    @MainActor
    private func checkCanAcceptAgentTask() -> Bool {
        // Check if any frontend operations are active that should block agentTasks
        let blockingAudioOwners = AudioCaptureService.activeRecordingOwners.filter { owner in
            owner != "agentTask"
        }
        if !blockingAudioOwners.isEmpty {
            #if DEBUG
            DevLogger.shared.info(
                "AgentTask blocked: microphone capture active for owner(s): \(blockingAudioOwners.joined(separator: ", "))",
                context: "websocket"
            )
            #endif
            return false
        }
        
        // Check transcription recording
        if let appDelegate = NSApplication.shared.delegate as? AppDelegate,
           let statusBarManager = appDelegate.statusBarManager {
            if statusBarManager.transcriptionController.isRecording {
                #if DEBUG
                DevLogger.shared.info("AgentTask blocked: transcription recording active", context: "websocket")
                #endif
                return false
            }
        }
        
        // Check AssistantSession recording
        if let assistantSessionViewModel = AssistantSessionWindowController.sharedController?.viewModel,
           assistantSessionViewModel.isRecording {
            #if DEBUG
            DevLogger.shared.info("AgentTask blocked: AssistantSession recording active", context: "websocket")
            #endif
            return false
        }
        
        // Check live transcription (if it uses audio capture)
        // Note: Live transcription might be system audio, but if it's recording microphone, block it
        // We can add this check if needed based on your live transcription implementation
        
        #if DEBUG
        DevLogger.shared.info("AgentTask allowed: no blocking operations detected", context: "websocket")
        #endif
        return true
    }
    
    @MainActor
    private func handleWidgetStateQuery(_ json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Processing widget state query from backend", context: "websocket")
        #endif
        
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("Widget state query missing request_id", context: "websocket")
            #endif
            return
        }
        
        // Get current widget state
        let widgetState = getWidgetState()
        
        // Send response back to backend
        var response: [String: Any] = [
            "type": "widget_state_response",
            "request_id": requestId,
            "can_accept_agent_task": widgetState.canAcceptAgentTask,
            "is_processing": widgetState.isProcessing,
            "has_completed_result": widgetState.hasCompletedResult,
            "timestamp": Date().timeIntervalSince1970
        ]
        
        // Include root_task_id if available
        if let rootTaskId = widgetState.rootTaskId {
            response["root_task_id"] = rootTaskId
        }
        
        if let responseData = try? JSONSerialization.data(withJSONObject: response),
           let responseString = String(data: responseData, encoding: .utf8) {
            sendMessage(responseString)
            #if DEBUG
            DevLogger.shared.info("Sent widget state response: \(response)", context: "websocket")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to serialize widget state response", context: "websocket")
            #endif
        }
    }
    
    /// Snapshot of the result-widget singleton's current focus state, used
    /// to answer backend `widget_state` queries.
    ///
    /// Reads directly from ``AgentTaskResultWidgetController/shared`` (which
    /// owns the persistent history/result widget) and its
    /// ``AgentTaskResultWidgetController/focusedRowState`` cache (which is
    /// pushed from the React sidebar on every focus change). The capture
    /// widget no longer owns any of this state — it's an ephemeral
    /// new-AgentTask-only surface and contributes nothing to widget_state.
    ///
    /// Decision table:
    ///   * Result widget not visible → `(canAccept, false, false, nil)`.
    ///   * Visible but no focused row, or focused row has no agentTaskId →
    ///     `(canAccept, false, false, nil)` (treat as new-capture path).
    ///   * Focused row processing → `(canAccept, true, false, nil)`.
    ///   * Focused row has result and is follow-up-eligible →
    ///     `(canAccept, false, true, focused.agentTaskId)`.
    @MainActor
    private func getWidgetState() -> (canAcceptAgentTask: Bool, isProcessing: Bool, hasCompletedResult: Bool, rootTaskId: String?) {
        let canAccept = checkCanAcceptAgentTask()

        let coordinator = AgentTaskResultPresentationCoordinator.shared
        guard coordinator.activePresenter != nil,
              let focused = coordinator.authoritativeFocusedRowState,
              let agentTaskId = focused.agentTaskId,
              !agentTaskId.isEmpty else {
            #if DEBUG
            DevLogger.shared.info(
                "Widget state: no result widget visible (or no focused row), canAccept=\(canAccept)",
                context: "websocket"
            )
            #endif
            return (canAccept, false, false, nil)
        }

        let isProcessing = focused.isProcessing
        let hasCompletedResult = focused.hasResult && !isProcessing && focused.supportsFollowUp
        let rootTaskId = hasCompletedResult ? agentTaskId : nil

        #if DEBUG
        DevLogger.shared.info(
            "Widget state: canAccept=\(canAccept), isProcessing=\(isProcessing), hasCompletedResult=\(hasCompletedResult), rootTaskId=\(rootTaskId ?? "nil")",
            context: "websocket"
        )
        #endif

        return (canAccept, isProcessing, hasCompletedResult, rootTaskId)
    }
} 