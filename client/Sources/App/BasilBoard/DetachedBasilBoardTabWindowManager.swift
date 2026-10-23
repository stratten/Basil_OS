import AppKit

/// Owns at most one native window per detached (non-Home) BasilBoard tab.
/// Only tabs in `boardWindowTabIds` may ever be detached; this mirrors the
/// independent allow-list check in `BasilBoardWebView.handleMessage`, so a
/// compromised or buggy web layer cannot make the native layer open an
/// arbitrary window.
@MainActor
final class DetachedBasilBoardTabWindowManager {
    static let boardWindowTabIds: Set<String> = ["meetings", "todos"]

    private var controllers: [String: BasilBoardWindowController] = [:]
    var onDetachedTabsChanged: (([String]) -> Void)?
    var onOpenMeetingWorkspaceRequested: ((String) -> Void)?

    var detachedTabIds: [String] {
        controllers.keys.sorted()
    }

    func openOrFocus(tabId: String) {
        openOrFocus(tabId: tabId, originType: nil, originId: nil)
    }

    func openOrFocus(tabId: String, originType: String?, originId: String?) {
        guard Self.boardWindowTabIds.contains(tabId) else {
            DevLogger.shared.error(
                "[DetachedBasilBoardTabWindowManager] Rejected unregistered Board-window tabId: \(tabId)",
                context: "BasilBoard"
            )
            return
        }
        if let existing = controllers[tabId] {
            existing.show()
            if let originType, let originId {
                existing.navigateToAgentTaskOrigin(originType: originType, originId: originId)
            }
            return
        }

        let controller = BasilBoardWindowController(detachedTabId: tabId)
        controller.onOpenMeetingWorkspaceRequested = { [weak self] meetingId in
            self?.onOpenMeetingWorkspaceRequested?(meetingId)
        }
        controller.onWindowClosed = { [weak self] in
            guard let self else { return }
            self.controllers.removeValue(forKey: tabId)
            self.onDetachedTabsChanged?(self.detachedTabIds)
        }
        controllers[tabId] = controller
        controller.show()
        if let originType, let originId {
            controller.navigateToAgentTaskOrigin(originType: originType, originId: originId)
        }
        onDetachedTabsChanged?(detachedTabIds)
    }

    func closeAll() {
        let existingControllers = Array(controllers.values)
        controllers.removeAll()
        for controller in existingControllers {
            controller.onWindowClosed = nil
            controller.dismiss()
        }
        onDetachedTabsChanged?(detachedTabIds)
    }
}
