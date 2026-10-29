import AppKit

/// Single entry point for "surface a running or completed AgentTask,
/// wherever the user is currently looking." Replaces every direct call to
/// `AgentTaskResultWidgetController.installNewAgent` /
/// `.showExistingAgentTask` / `.showStandaloneHistory` so all five call
/// sites (hotkey capture handoff, meeting action proposals, ambient
/// suggestions, setup assistant, and the Board's own deep-link bridge
/// message) apply the identical authority rule: if the Board is currently
/// authoritative (embedded host live, standalone not visible), fold the
/// AgentTask into the embedded host; otherwise fall back to the standalone
/// widget, creating it if necessary. This mirrors
/// `AgentTaskResultPresentationCoordinator`'s existing "standalone always
/// wins when visible" rule -- it does not introduce a second rule.
@MainActor
enum AgentTaskResultPresentationRouter {
    @discardableResult
    static func installNewAgent(
        agentTaskId: String,
        initialAgentTask: String?,
        anchorFrame: NSRect? = nil,
        placement: AgentTaskResultWidgetController.Placement? = nil,
        initialReferencePaths: [URL] = []
    ) -> Bool {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        if coordinator.activePresenter == .board, let host = coordinator.activeEmbeddedHost {
            host.dispatchOrQueueWebCommand(.register(agentTaskId: agentTaskId, referencePaths: initialReferencePaths))
            return true
        }
        AgentTaskResultWidgetController.installNewAgent(
            agentTaskId: agentTaskId,
            initialAgentTask: initialAgentTask,
            anchorFrame: anchorFrame,
            placement: placement,
            initialReferencePaths: initialReferencePaths
        )
        return false
    }

    static func showExistingAgentTask(agentTaskId: String, anchorFrame: NSRect? = nil) {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        if coordinator.activePresenter == .board, let host = coordinator.activeEmbeddedHost {
            host.dispatchOrQueueWebCommand(.showExisting(agentTaskId: agentTaskId))
            return
        }
        AgentTaskResultWidgetController.showExistingAgentTask(agentTaskId: agentTaskId, anchorFrame: anchorFrame)
    }
}
