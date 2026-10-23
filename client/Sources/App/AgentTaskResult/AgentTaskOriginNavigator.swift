import AppKit

@MainActor
enum AgentTaskOriginNavigator {
    @discardableResult
    static func open(originType: String, originId: String, originatingWindow: NSWindow?) -> Bool {
        guard !originId.isEmpty else { return false }

        switch originType {
        case "conversation":
            return ConversationPresentationRouter.showConversation(
                conversationId: originId,
                originatingWindow: originatingWindow
            )
        case "todo", "todo_workspace":
            return openBasilBoardTab("todos", originType: originType, originId: originId)
        case "scheduled_task":
            let controller = AgentTaskResultWidgetController.showStandaloneHistory()
            controller.dispatchOrQueueWebCommand(.showScheduled(scheduledAgentTaskId: originId))
            return true
        case "meeting":
            guard let coordinator = statusBarWindowCoordinator() else { return false }
            coordinator.openMeetingWorkspace(meetingId: originId)
            return true
        default:
            return false
        }
    }

    private static func openBasilBoardTab(_ tabId: String, originType: String, originId: String) -> Bool {
        guard let coordinator = statusBarWindowCoordinator() else { return false }
        coordinator.openBasilBoardAgentTaskOriginTab(
            tabId: tabId,
            originType: originType,
            originId: originId
        )
        return true
    }

    private static func statusBarWindowCoordinator() -> StatusBarWindowCoordinator? {
        (NSApp.delegate as? AppDelegate)?.statusBarManager?.windowCoordinator
    }
}
