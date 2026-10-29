import Foundation

/// A request from the backend to collect a connection token from the user in Paprika's overlay.
///
/// The backend sends `connection_secret_request` when the agent connects a service that gives out a bearer token. The reply, `connection_secret_result`, carries only a status, never the token.
struct ConnectionSecretRequest: Equatable {
    let requestId: String
    let serverUrl: String
    let friendlyName: String
    let description: String?
    /// Names of the connections already saved; the overlay refuses to reuse one.
    let existingNames: [String]
    /// The name of a connection that already uses this address, so the overlay can say a second one is being added.
    let alreadyConnectedAs: String?

    /// Returns nil unless the message names a request and a public-looking https address. The check repeats the backend's, so a malformed message can never collect a token for somewhere unexpected.
    static func parse(_ json: [String: Any]) -> ConnectionSecretRequest? {
        guard let requestId = json["request_id"] as? String, !requestId.isEmpty,
              let serverUrl = json["server_url"] as? String,
              let components = URLComponents(string: serverUrl),
              components.scheme?.lowercased() == "https",
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil else {
            return nil
        }
        let rawName = (json["friendly_name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let rawDescription = (json["description"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return ConnectionSecretRequest(
            requestId: requestId,
            serverUrl: serverUrl,
            friendlyName: rawName.isEmpty ? host : rawName,
            description: (rawDescription?.isEmpty ?? true) ? nil : rawDescription,
            existingNames: (json["existing_names"] as? [Any])?.compactMap { $0 as? String } ?? [],
            alreadyConnectedAs: (json["already_connected_as"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        )
    }
}

enum WebSocketService_ConnectionSecret {
    /// The `connection_secret_result` text for the backend. It never includes the token.
    static func resultMessage(
        requestId: String,
        outcome: ConnectionTokenConnector.Outcome?,
        lastFailureMessage: String?
    ) -> String? {
        var payload: [String: Any] = [
            "type": "connection_secret_result",
            "request_id": requestId
        ]
        switch outcome {
        case .connected(let connectionId, let toolCount, let friendlyName, let description):
            payload["status"] = "connected"
            payload["connection_id"] = connectionId
            payload["tool_count"] = toolCount
            payload["friendly_name"] = friendlyName
            if let description {
                payload["description"] = description
            }
        case .failed(let message):
            payload["status"] = "failed"
            payload["message"] = message
        case nil:
            if let lastFailureMessage {
                payload["status"] = "failed"
                payload["message"] = lastFailureMessage
            } else {
                payload["status"] = "canceled"
            }
        }
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Remembers the host-socket reply for `connection_secret_request`. The form is shown in Paprika, not in a separate window.
    @MainActor
    static func handleRequest(_ json: [String: Any], send: @escaping (String) -> Void) {
        guard let request = ConnectionSecretRequest.parse(json) else {
            DevLogger.shared.error("🔐 Ignored a malformed connection_secret_request", context: "websocket")
            if let requestId = json["request_id"] as? String, !requestId.isEmpty,
               let reply = resultMessage(requestId: requestId, outcome: .failed(message: "The Basil app rejected the connection request as malformed."), lastFailureMessage: nil) {
                send(reply)
            }
            return
        }
        ConnectionTokenEntryCoordinator.shared.remember(request, send: send)
    }

    /// Drops a token form the backend no longer waits for.
    @MainActor
    static func handleCancel(_ json: [String: Any]) {
        guard let requestId = json["request_id"] as? String else { return }
        ConnectionTokenEntryCoordinator.shared.dismiss(requestId: requestId)
    }
}
