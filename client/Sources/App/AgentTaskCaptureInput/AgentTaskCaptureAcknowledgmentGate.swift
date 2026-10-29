import Foundation

/// One-shot record that the capture widget was shown by the hotkey before the backend answered.
///
/// The backend later broadcasts `agent_task_capture_started` for the same press. `WebSocketService.handleAgentTaskStarted` normally treats that event as "a capture is already running, so complete it", which would end the capture the hotkey just opened. While this gate is armed, the first matching event is consumed instead.
///
/// The deadline is a safety bound only. It stops a lost acknowledgment from swallowing a later, unrelated wake-word event, and it stops a very late backend refusal from closing a widget the user has been speaking into. The normal path consumes the gate when the real event arrives.
struct AgentTaskCaptureAcknowledgmentGate {
    static let timeoutSeconds: TimeInterval = 5

    private(set) var deadline: Date?

    var isAwaiting: Bool { deadline != nil }

    mutating func begin(now: Date) {
        deadline = now.addingTimeInterval(Self.timeoutSeconds)
    }

    /// Returns true exactly once per `begin`, and only when called at or before the deadline. The gate is always disarmed afterwards.
    mutating func consume(now: Date) -> Bool {
        defer { deadline = nil }
        guard let deadline else { return false }
        return now <= deadline
    }
}
