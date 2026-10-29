import Foundation

extension AgentTaskCaptureInputWindowController {
    /// Arms the acknowledgment gate for a panel the hotkey showed ahead of the backend.
    func beginAwaitingBackendAcknowledgment(now: Date = Date()) {
        backendAcknowledgmentGate.begin(now: now)
    }

    /// Consumes the gate on the active capture panel. Returns true when the backend's `agent_task_capture_started` event is the acknowledgment of a hotkey that already showed the panel.
    static func consumeBackendAcknowledgment(now: Date = Date()) -> Bool {
        activeController?.backendAcknowledgmentGate.consume(now: now) ?? false
    }

    /// Quietly closes a panel the hotkey showed when the backend declined or could not be reached.
    ///
    /// Does nothing once the acknowledgment arrived or the deadline passed. The backend owns no state for a declined press, so the close does not send `agent_task_widget_closed` and the capture is canceled without posting `stop-agent-task-capture`. Either message could end or resume a capture that is legitimately running.
    func dismissAfterBackendRejection(now: Date = Date()) {
        guard backendAcknowledgmentGate.consume(now: now) else { return }
        guard let viewModel else { return }
        didNotifyBackendWidgetClosed = true
        viewModel.cancelCaptureWithoutBackendNotification()
    }
}
