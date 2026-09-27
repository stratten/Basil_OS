import Foundation

@MainActor
enum BasilBoardNativeTabWindowRegistry {
    typealias WindowOpener = @MainActor () -> Void

    private static let productionOpeners: [String: WindowOpener] = [
        "chats": {
            ConversationWidgetManager.shared.show()
        },
        "agent_tasks": {
            AgentTaskResultWidgetController.showStandaloneHistory()
        },
    ]

    @discardableResult
    static func open(
        tabId: String,
        openers: [String: WindowOpener]? = nil
    ) -> Bool {
        let registry = openers ?? productionOpeners
        guard let opener = registry[tabId] else {
            DevLogger.shared.error(
                "[BasilBoardNativeTabWindowRegistry] Rejected unregistered native tabId: \(tabId)",
                context: "BasilBoard"
            )
            return false
        }
        opener()
        return true
    }
}
