import AppKit

extension AgentTaskResultEmbeddedHost {
    func ensureProvisionalFailureObserver() {
        guard provisionalFailureObserver == nil else { return }
        provisionalFailureObserver = NotificationCenter.default.addObserver(
            forName: Notification.Name("AgentTaskProvisionalFailed"),
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let info = note.userInfo as? [String: Any] else { return }
            guard let agentTaskId = info["agentTaskId"] as? String, !agentTaskId.isEmpty else { return }
            let reason = (info["reason"] as? String) ?? "unknown"
            let message = (info["message"] as? String) ?? "Audio could not be processed."
            let rootTaskId = info["rootTaskId"] as? String
            let previousTaskId = info["previousTaskId"] as? String
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                #if DEBUG
                DevLogger.shared.info(
                    "[AgentTaskResultEmbeddedHost] Forwarding provisional failure for \(agentTaskId) (reason=\(reason)) to React",
                    context: "AgentTaskResult"
                )
                #endif
                self.webView.sendProvisionalFailed(
                    agentTaskId: agentTaskId,
                    reason: reason,
                    message: message,
                    rootTaskId: rootTaskId,
                    previousTaskId: previousTaskId
                )
            }
        }
    }
}
