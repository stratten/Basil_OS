import AppKit

private struct WeakDetachedThreadsObserver {
    weak var value: ConversationDetachedThreadsObserver?
    init(_ value: ConversationDetachedThreadsObserver) { self.value = value }
}

@MainActor
final class DetachedConversationThreadWindowManager {
    static let shared = DetachedConversationThreadWindowManager()

    private var controllers: [String: DetachedConversationThreadWindowController] = [:]
    private var observers: [ObjectIdentifier: WeakDetachedThreadsObserver] = [:]

    var detachedConversationIds: [String] {
        controllers.keys.sorted()
    }

    func addObserver(_ observer: ConversationDetachedThreadsObserver) {
        observers[ObjectIdentifier(observer)] = WeakDetachedThreadsObserver(observer)
    }

    func removeObserver(_ observer: ConversationDetachedThreadsObserver) {
        observers.removeValue(forKey: ObjectIdentifier(observer))
    }

    func hasOpenThread(conversationId: String) -> Bool {
        controllers[conversationId] != nil
    }

    @discardableResult
    func focusExistingThread(conversationId: String) -> Bool {
        guard let controller = controllers[conversationId] else { return false }
        controller.bringToFront()
        return true
    }

    func open(conversationId: String, originatingWindow: NSWindow? = nil) {
        guard !conversationId.isEmpty else { return }
        if focusExistingThread(conversationId: conversationId) {
            notifyDetachedConversationsChanged()
            return
        }
        let visibleFrame = originatingWindow?.screen?.visibleFrame
            ?? NSScreen.main?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let sourceFrame = originatingWindow?.frame
            ?? NSRect(x: visibleFrame.midX - 300, y: visibleFrame.midY - 220, width: 600, height: 440)
        let frame = NSRect(
            x: min(max(visibleFrame.minX, sourceFrame.minX + 28), visibleFrame.maxX - 600),
            y: min(max(visibleFrame.minY, sourceFrame.minY - 28), visibleFrame.maxY - 440),
            width: 600,
            height: 440
        )
        let controller = DetachedConversationThreadWindowController(
            conversationId: conversationId,
            initialFrame: frame
        ) { [weak self] closedConversationId in
            guard let self else { return }
            self.controllers.removeValue(forKey: closedConversationId)
            self.notifyDetachedConversationsChanged()
        }
        controllers[conversationId] = controller
        controller.show()
        notifyDetachedConversationsChanged()
    }

    private func notifyDetachedConversationsChanged() {
        let conversationIds = detachedConversationIds
        for (id, box) in observers {
            guard let observer = box.value else {
                observers.removeValue(forKey: id)
                continue
            }
            observer.updateDetachedConversationIds(conversationIds)
        }
    }
}
