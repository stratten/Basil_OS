import Foundation

/// Remembers the host-socket reply for a token-connect request. The form itself is the Paprika overlay; this type never opens a window.
@MainActor
final class ConnectionTokenEntryCoordinator {
    static let shared = ConnectionTokenEntryCoordinator()

    private struct Entry {
        let request: ConnectionSecretRequest
        let send: (String) -> Void
        var isWorking = false
        var lastFailureMessage: String?
    }

    private var entries: [String: Entry] = [:]

    /// Number of token forms still waiting for an answer (used by tests).
    var pendingCount: Int { entries.count }

    func remember(_ request: ConnectionSecretRequest, send: @escaping (String) -> Void) {
        if entries[request.requestId] != nil { return }
        entries[request.requestId] = Entry(request: request, send: send)
    }

    /// Drops a request the backend no longer waits for. No reply is sent.
    func dismiss(requestId: String) {
        entries.removeValue(forKey: requestId)
    }

    func submit(
        requestId: String,
        friendlyName: String,
        description: String?,
        token: String,
        notify: @escaping ([String: Any]) -> Void
    ) {
        guard var entry = entries[requestId] else {
            notify([
                "requestId": requestId,
                "status": "failed",
                "message": "This connection request is no longer waiting.",
            ])
            return
        }
        entry.isWorking = true
        entries[requestId] = entry
        let serverUrl = entry.request.serverUrl
        Task { @MainActor in
            let outcome = await ConnectionTokenConnector().connect(
                serverUrl: serverUrl,
                friendlyName: friendlyName,
                description: description,
                token: token
            )
            guard var latest = self.entries[requestId] else { return }
            latest.isWorking = false
            switch outcome {
            case .connected:
                self.entries[requestId] = latest
                self.finish(requestId: requestId, outcome: outcome)
                notify(["requestId": requestId, "status": "connected"])
            case .failed(let message):
                latest.lastFailureMessage = message
                self.entries[requestId] = latest
                notify(["requestId": requestId, "status": "failed", "message": message])
            }
        }
    }

    func cancel(requestId: String) {
        finish(requestId: requestId, outcome: nil)
    }

    private func finish(requestId: String, outcome: ConnectionTokenConnector.Outcome?) {
        guard let entry = entries.removeValue(forKey: requestId) else { return }
        if let reply = WebSocketService_ConnectionSecret.resultMessage(
            requestId: requestId,
            outcome: outcome,
            lastFailureMessage: entry.lastFailureMessage
        ) {
            entry.send(reply)
        }
    }
}
