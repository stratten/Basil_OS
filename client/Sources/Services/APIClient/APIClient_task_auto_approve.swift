import Foundation

/// The state the backend reports for a task's auto-approve switch after a change.
struct TaskAutoApproveOutcome: Equatable {
    let enabled: Bool
    /// How many cards the task was already waiting on that turning the switch on approved.
    let approvedWaiting: Int

    /// Reads the backend's `{"enabled": Bool, "approved_waiting": Int}` answer. A body without a boolean `enabled` is not an answer.
    static func decode(_ data: Data) throws -> TaskAutoApproveOutcome {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let enabled = object["enabled"] as? Bool else {
            throw APIError.invalidResponse
        }
        let approvedWaiting = (object["approved_waiting"] as? Int) ?? 0
        return TaskAutoApproveOutcome(enabled: enabled, approvedWaiting: max(0, approvedWaiting))
    }
}

extension APIClient {
    /// The route for one task chain's switch. The id is a single path segment, so a slash or other reserved character in it must not change which route is reached.
    static func taskAutoApproveEndpoint(rootTaskId: String) -> String? {
        let trimmed = rootTaskId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/")
        guard let segment = trimmed.addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
        return "/api/v1/agent-tasks/auto-approve/\(segment)"
    }

    /// Turns a task chain's auto-approve switch on or off. Turning it on needs the user's confirmation, which `postConfirmingExecutionApprovalRisk` asks for in a native alert; declining throws `ExecutionApprovalRiskConfirmationError.declined` and nothing changes.
    func setTaskAutoApprove(rootTaskId: String, enabled: Bool) async throws -> TaskAutoApproveOutcome {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        guard let endpoint = Self.taskAutoApproveEndpoint(rootTaskId: rootTaskId) else {
            throw APIError.invalidURL
        }
        let body = try JSONSerialization.data(withJSONObject: ["enabled": enabled], options: [])
        let data = try await postConfirmingExecutionApprovalRisk(endpoint, body: body)
        return try TaskAutoApproveOutcome.decode(data)
    }
}
