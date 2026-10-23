import AppKit

extension AgentTaskResultWidgetController {
    static let collapsedRunRailWidth: CGFloat = 44
    static let standaloneCollapsedDefaultWidth: CGFloat = 444
    static let standaloneCollapsedMinimumWidth: CGFloat = 444
    static let standaloneSidebarExpansionWidth: CGFloat = 192

    @MainActor static func standaloneMinimumWidth(
        sidebarExpanded: Bool,
        rightAccessoryWidth: CGFloat? = nil
    ) -> CGFloat {
        (standaloneCollapsedMinimumWidth - collapsedRunRailWidth)
            + (sidebarExpanded ? standaloneSidebarExpansionWidth : 0)
            + (rightAccessoryWidth ?? collapsedRunRailWidth)
    }

    @MainActor static func standaloneMinimumSize(sidebarExpanded: Bool) -> NSSize {
        NSSize(width: standaloneMinimumWidth(sidebarExpanded: sidebarExpanded), height: 300)
    }

    @MainActor static func standaloneInitialSize(sidebarExpanded _: Bool) -> NSSize {
        NSSize(
            width: standaloneCollapsedDefaultWidth,
            height: 400
        )
    }

    enum Placement {
        case anchoredLeftOfFrame(NSRect)
        case topRightCurrentScreen
        case topRightScreenContainingFrame(NSRect)
        case topRightLeavingCaptureSpace
    }

    /// Snapshot of the row currently highlighted in the React sidebar,
    /// pushed from JS via ``agentStatusChanged``. Read by the agentTask
    /// hotkey handler to decide whether to start a follow-up or a new
    /// capture.
    struct FocusedRowState {
        let agentTaskId: String?
        let isProcessing: Bool
        let hasResult: Bool
        let supportsFollowUp: Bool
    }

    enum PendingWebCommand {
        case register(agentTaskId: String, referencePaths: [URL] = [])
        case showExisting(agentTaskId: String)
        case showScheduled(scheduledAgentTaskId: String)
        case restoreValidationManagedHistory(requestId: String)
        case detachedRoots(rootTaskIds: [String])
    }
}
