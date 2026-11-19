import Foundation

extension AgentTaskCaptureViewModel {
    /// The chain this capture's task belongs to: the existing chain for a follow-up, otherwise the id generated for the new task up front, which becomes its root.
    var autoApproveChainRootId: String? {
        let candidate = rootTaskId ?? preGeneratedAgentTaskId
        guard let candidate, !candidate.isEmpty else { return nil }
        return candidate
    }

    /// Asks for this capture's task to run with auto-approve on or off. The task does not exist yet, but its chain root does, so the switch is set against that id and is already in force when the task's first command asks.
    func setTaskAutoApprove(
        _ enabled: Bool,
        change: @escaping TaskAutoApproveBridge.Change = TaskAutoApproveBridge.liveChange
    ) async {
        guard !taskAutoApprovePending,
              enabled != taskAutoApproveEnabled,
              let rootTaskId = autoApproveChainRootId else {
            return
        }
        taskAutoApprovePending = true
        taskAutoApproveError = nil
        let result = await TaskAutoApproveBridge.perform(
            requestId: "capture-\(rootTaskId)",
            rootTaskId: rootTaskId,
            enabled: enabled,
            change: change
        )
        if result.status == .applied {
            taskAutoApproveEnabled = result.enabled
        }
        taskAutoApproveError = result.status == .failed ? result.message : nil
        taskAutoApprovePending = false
    }
}
