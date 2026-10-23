import Foundation

final class WebSocketService_Conversation {
    unowned let parent: WebSocketService

    init(parent: WebSocketService) {
        self.parent = parent
    }

    @MainActor
    func handleHistoryChatEvent(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Broadcasting history_chat_event from event_type", context: "websocket")
        // Log the full event data for debugging
        if let message = json["message"] as? String {
            DevLogger.shared.info("History chat message content: '\(message)'", context: "websocket")
        }
        if let messageType = json["message_type"] as? String {
            DevLogger.shared.info("History chat message type: '\(messageType)'", context: "websocket")
        }
        if let isLoading = json["is_loading"] as? Bool {
            DevLogger.shared.info("History chat is_loading: \(isLoading)", context: "websocket")
        }
        if let messageId = json["message_id"] as? String {
            DevLogger.shared.info("History chat message_id: \(messageId)", context: "websocket")
        }
        #endif
        // Check if this is an error message
        if let messageType = json["message_type"] as? String, messageType == "error" {
            #if DEBUG
            DevLogger.shared.warning("Received error message in history_chat_event: \(json)", context: "websocket")
            #endif
        }
        Task { @MainActor in
            #if DEBUG
            DevLogger.shared.info("Emitting .conversationEvent to eventSubject: \(json)", context: "websocket")
            #endif
            parent.eventSubject.send(.conversationEvent(json))
        }
    }

    @MainActor
    func handleConversationToken(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Received conversation_token event", context: "websocket")
        if let token = json["token"] as? String {
            let truncatedToken = token.count > 10 ? token.prefix(10) + "..." : token
            DevLogger.shared.info("Token content: '\(truncatedToken)'", context: "websocket")
        }
        if let messageId = json["message_id"] as? String {
            DevLogger.shared.info("Token for message_id: \(messageId)", context: "websocket")
        }
        if let isFinal = json["is_final"] as? Bool, isFinal {
            DevLogger.shared.info("Final token in stream", context: "websocket")
            DevLogger.shared.info("Stream completed successfully", context: "websocket")
        }
        if let chunkId = json["chunk_id"] {
            DevLogger.shared.info("Token chunk_id: \(chunkId)", context: "websocket")
        }
        #endif
        parent.eventSubject.send(.conversationEvent(json))
    }

    @MainActor
    func handleConversationMessage(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Received conversation_message event", context: "websocket")
        #endif
        Task { @MainActor in
            parent.eventSubject.send(.conversationEvent(json))
        }
    }

    @MainActor
    func handleConversationError(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.warning("Received conversation_error event: \(json)", context: "websocket")
        #endif
        Task { @MainActor in
            parent.eventSubject.send(.conversationEvent(json))
        }
    }

    @MainActor
    func handleConversationToggled(json: [String: Any]) {
        #if DEBUG
        DevLogger.shared.info("Broadcasting conversation_toggled event from event_type", context: "websocket")
        #endif
        // Check if this is an error message
        if let messageType = json["message_type"] as? String, messageType == "error" {
            #if DEBUG
            DevLogger.shared.warning("Received error message in conversation_toggled event: \(json)", context: "websocket")
            #endif
        }
        Task { @MainActor in
            parent.eventSubject.send(.conversationEvent(json))
        }
    }

    @MainActor
    func handleWebSocketMessage(_ json: [String: Any]) {
        if let eventType = json["event_type"] as? String {
            switch eventType {
            case "history_chat_event":
                handleHistoryChatEvent(json: json)
            case "conversation_token":
                handleConversationToken(json: json)
            case "conversation_message":
                handleConversationMessage(json: json)
            case "conversation_error":
                handleConversationError(json: json)
            case "conversation_toggled":
                handleConversationToggled(json: json)
            // Add other conversation events as needed
            default:
                break
            }
        }
    }
} 