import Foundation

/// How a request to change a task's auto-approve switch ended, in the shape both web surfaces receive it.
struct TaskAutoApproveBridgeResult: Equatable {
    enum Status: String {
        /// The backend accepted the change.
        case applied
        /// The user said no in the native confirmation. Nothing changed, and this is not an error.
        case declined
        /// The change could not be made, such as the backend not running.
        case failed
    }

    let requestId: String
    let rootTaskId: String
    let status: Status
    /// The switch's state after the attempt. A declined or failed attempt leaves it where it was.
    let enabled: Bool
    let approvedWaiting: Int
    let message: String?

    /// The `TaskAutoApproveResult` the web side expects.
    var jsonObject: [String: Any] {
        var object: [String: Any] = [
            "requestId": requestId,
            "rootTaskId": rootTaskId,
            "status": status.rawValue,
            "enabled": enabled,
            "approvedWaiting": approvedWaiting,
        ]
        if let message {
            object["message"] = message
        }
        return object
    }
}

/// Turns a request from a web surface into a backend change and a result to hand back. The change is injected so tests do not need the backend or the native alert.
enum TaskAutoApproveBridge {
    typealias Change = (_ rootTaskId: String, _ enabled: Bool) async throws -> TaskAutoApproveOutcome

    static let failureMessage = "Auto-approve could not be changed."

    static let liveChange: Change = { rootTaskId, enabled in
        try await APIClient.shared.setTaskAutoApprove(rootTaskId: rootTaskId, enabled: enabled)
    }

    /// Asks for the change and reports how it ended. Web surfaces only ask for a state the switch is not already in, so when an attempt does not go through the switch is reported as the opposite of what was asked.
    static func perform(
        requestId: String,
        rootTaskId: String,
        enabled: Bool,
        change: Change = liveChange
    ) async -> TaskAutoApproveBridgeResult {
        do {
            let outcome = try await change(rootTaskId, enabled)
            return TaskAutoApproveBridgeResult(
                requestId: requestId,
                rootTaskId: rootTaskId,
                status: .applied,
                enabled: outcome.enabled,
                approvedWaiting: outcome.approvedWaiting,
                message: nil
            )
        } catch ExecutionApprovalRiskConfirmationError.declined {
            return TaskAutoApproveBridgeResult(
                requestId: requestId,
                rootTaskId: rootTaskId,
                status: .declined,
                enabled: !enabled,
                approvedWaiting: 0,
                message: nil
            )
        } catch {
            DevLogger.shared.error("Could not change a task's auto-approve switch: \(error.localizedDescription)", context: "TaskAutoApprove")
            return TaskAutoApproveBridgeResult(
                requestId: requestId,
                rootTaskId: rootTaskId,
                status: .failed,
                enabled: !enabled,
                approvedWaiting: 0,
                message: failureMessage
            )
        }
    }
}
