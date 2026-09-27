import AppKit

@MainActor
enum ConversationPresentationRouter {
    enum Destination: Equatable {
        case standalone
        case board
        case detached
    }

    @discardableResult
    static func showConversation(conversationId: String, originatingWindow: NSWindow? = nil) -> Bool {
        guard !conversationId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }

        switch destination(
            presenter: ConversationPresentationCoordinator.shared.activePresenter,
            hasDetachedThread: DetachedConversationThreadWindowManager.shared.hasOpenThread(conversationId: conversationId)
        ) {
        case .standalone:
            ConversationWidgetManager.shared.show(conversationId: conversationId)
        case .board:
            guard let coordinator = statusBarWindowCoordinator() else {
                return false
            }
            coordinator.openBasilBoardConversationOrigin(originId: conversationId)
        case .detached:
            guard DetachedConversationThreadWindowManager.shared.focusExistingThread(conversationId: conversationId) else {
                return false
            }
        }

        return true
    }

    static func destination(
        presenter: ConversationPresentationOwner?,
        hasDetachedThread: Bool
    ) -> Destination {
        switch presenter {
        case .standalone:
            return .standalone
        case .board:
            return .board
        case nil:
            return hasDetachedThread ? .detached : .standalone
        }
    }

    private static func statusBarWindowCoordinator() -> StatusBarWindowCoordinator? {
        (NSApp.delegate as? AppDelegate)?.statusBarManager?.windowCoordinator
    }
}
