import Foundation
import AppKit

final class WebSocketService_GenericHandlers {
    @MainActor
    static func handleWebSocketError(_ error: Error, parent: WebSocketService) {
        #if DEBUG
        DevLogger.shared.error("WebSocket receive error: \(error)", context: "websocket")
        #endif
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
            // This is a normal cancellation, likely due to a deliberate disconnect
            // Don't trigger reconnect for cancellations
            DevLogger.shared.info("WebSocket received cancellation error - normal during disconnect/reconnect", context: "websocket")
        } else if nsError.domain == "WebSocketError" &&
                  (nsError.code == Int(URLSessionWebSocketTask.CloseCode.normalClosure.rawValue) ||
                   nsError.code == Int(URLSessionWebSocketTask.CloseCode.goingAway.rawValue)) {
            // Normal closure or going away - don't reconnect
            DevLogger.shared.info("WebSocket closed normally", context: "websocket")
            parent.isConnected = false
        } else {
            // For other errors, attempt to reconnect
            DevLogger.shared.warning("WebSocket error requires reconnect: \(error)", context: "websocket")
            Task { @MainActor in
                await parent.handleDisconnect()
            }
        }
    }

    static func handleWebSocketData(_ data: Data) {
        #if DEBUG
        DevLogger.shared.info("Received WebSocket binary message of size: \(data.count)", context: "websocket")
        #endif
    }

    static func handleUnknownWebSocketMessageType() {
        #if DEBUG
        DevLogger.shared.warning("Received unknown WebSocket message type", context: "websocket")
        #endif
    }

    @MainActor
    static func handleWebSocketMessage(_ json: [String: Any]) {
        // Log every single WebSocket message for debugging
        DevLogger.shared.info("📥 WEBSOCKET MESSAGE RECEIVED: \(json)", context: "websocket")
        
        // AgentTask events are now handled by WebSocketService_AgentTask
        
        if let status = json["status"] as? String {
            // Handle status/action responses
            if let message = json["message"] as? String {
                print("📊 Action response: \(status) - \(message)")
            } else {
                print("📊 Action response: \(status)")
            }
        } else {
            // Optionally log unknown/unhandled events
            #if DEBUG
            DevLogger.shared.warning("Unhandled or unknown WebSocket JSON message: \(json)", context: "websocket")
            #endif
        }
    }
} 