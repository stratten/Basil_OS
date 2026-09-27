import AppKit

@MainActor
final class BasilBoardWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSWindow?
    private var webViewHost: BasilBoardWebView?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var collapseController: WindowCollapseController?
    // 68 = 60 (.basil-board-header's min-height in shell.css, sized so its
    // 44px bubble gets even 8px padding above and below) + 8 (4px top + 4px
    // bottom .basil-webkit-window-frame inset drawn inside the webview). This
    // native window height and that CSS min-height must be kept in sync: the
    // window is a fixed size while collapsed, so if it's shorter than the
    // header wants, the header's bottom padding gets silently clipped.
    private let collapsedHeaderHeight: CGFloat = 68
    private let collapsedHeaderWidth: CGFloat = 300
    let detachedTabId: String?

    /// Fired once when this window transitions from open to closed (guarded
    /// against double-fire by `dismiss()`'s own `panel != nil` check). Used
    /// by `DetachedBasilBoardTabWindowManager` to drop its map entry; unused
    /// (nil) for the single main-board instance.
    var onWindowClosed: (() -> Void)?
    var onDetachTabRequested: ((String) -> Void)?
    var onBringTabToFrontRequested: ((String) -> Void)?
    var onOpenMeetingWorkspaceRequested: ((String) -> Void)?

    init(detachedTabId: String? = nil) {
        self.detachedTabId = detachedTabId
        super.init()
    }

    private static func windowSize(forDetachedTabId detachedTabId: String?) -> NSSize {
        switch detachedTabId {
        case "todos":
            return NSSize(width: 1120, height: 720)
        case "meetings":
            // Matches MeetingAssistantWindowController's own standalone panel
            // size, since the embedded Meeting Assistant content is the same
            // two-column (history sidebar + main column) layout and needs the
            // same width to avoid a cramped, broken-looking presentation.
            return NSSize(width: 860, height: 640)
        case .some:
            return NSSize(width: 480, height: 680)
        case .none:
            return NSSize(width: 1120, height: 720)
        }
    }

    private static func minimumWindowSize(forDetachedTabId detachedTabId: String?) -> NSSize {
        switch detachedTabId {
        case "todos":
            return NSSize(width: 970, height: 520)
        case "meetings":
            // Matches LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: false),
            // the same minimum the standalone Meeting Assistant panel enforces.
            return NSSize(width: 826, height: 606)
        case .some:
            return NSSize(width: 360, height: 420)
        case .none:
            return NSSize(width: 760, height: 520)
        }
    }

    private static func windowTitle(forDetachedTabId detachedTabId: String?) -> String {
        switch detachedTabId {
        case "chats": return "Basil — Chats"
        case "meetings": return "Basil — Meetings"
        case "todos": return "Basil — To-Dos"
        default: return "Basil"
        }
    }

    func setDetachedTabIds(_ tabIds: [String]) {
        webViewHost?.setDetachedTabIds(tabIds)
    }

    @discardableResult
    func navigateToAgentTaskOrigin(originType: String, originId: String) -> Bool {
        guard let webViewHost else { return false }
        return webViewHost.navigateToAgentTaskOrigin(originType: originType, originId: originId)
    }

    var isVisible: Bool { panel?.isVisible == true }
    var isFrontmost: Bool { panel?.isKeyWindow == true }

    /// Hides the board without tearing down its WebView, so reopening is instant.
    func hide() {
        panel?.orderOut(nil)
    }

    func show() {
        if let panel {
            if panel.isMiniaturized { panel.deminiaturize(nil) }
            NSApp.activate(ignoringOtherApps: true)
            panel.makeKeyAndOrderFront(nil)
            panel.orderFrontRegardless()
            return
        }

        let size = Self.windowSize(forDetachedTabId: detachedTabId)
        let newPanel = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: size.width, height: size.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        newPanel.title = Self.windowTitle(forDetachedTabId: detachedTabId)
        newPanel.isReleasedWhenClosed = false
        newPanel.level = .floating
        newPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        newPanel.hidesOnDeactivate = false
        newPanel.alphaValue = 1.0
        newPanel.isMovableByWindowBackground = true
        newPanel.minSize = Self.minimumWindowSize(forDetachedTabId: detachedTabId)
        newPanel.delegate = self
        keyboardShortcuts = WindowKeyboardShortcuts(window: newPanel)
        collapseController = WindowCollapseController(
            window: newPanel,
            compactSize: NSSize(width: collapsedHeaderWidth, height: collapsedHeaderHeight),
            fallbackExpandedSize: Self.windowSize(forDetachedTabId: detachedTabId)
        )
        centerPanel(newPanel, size: size)

        let host = BasilBoardWebView(detachedTabId: detachedTabId)
        host.hostWindow = newPanel
        host.onClose = { [weak self] in self?.dismiss() }
        host.onMinimize = { [weak newPanel] in newPanel?.miniaturize(nil) }
        host.onCollapseRequested = { [weak self] in self?.setCollapsed(true) }
        host.onExpandRequested = { [weak self] in self?.setCollapsed(false) }
        host.onReady = { [weak host] in
            guard let host else { return }
            fadeInWebViewContent(host.webView)
        }
        host.onDetachTab = { [weak self] tabId in self?.onDetachTabRequested?(tabId) }
        host.onBringTabToFront = { [weak self] tabId in self?.onBringTabToFrontRequested?(tabId) }
        host.onOpenMeetingWorkspace = { [weak self] meetingId in self?.onOpenMeetingWorkspaceRequested?(meetingId) }

        host.webView.frame = NSRect(origin: .zero, size: size)
        host.webView.autoresizingMask = [.width, .height]
        host.webView.alphaValue = 0

        newPanel.contentView = host.webView
        applyWebViewWindowAppearance(for: newPanel)
        host.installDragArea()
        host.loadContent()
        panel = newPanel
        webViewHost = host
        AppearanceRefreshCoordinator.shared.register(self)
        NSApp.activate(ignoringOtherApps: true)
        newPanel.makeKeyAndOrderFront(nil)
        newPanel.orderFrontRegardless()
    }

    func dismiss() {
        guard panel != nil else { return }
        panel?.orderOut(nil)
        webViewHost?.tearDown()
        panel = nil
        webViewHost = nil
        keyboardShortcuts = nil
        collapseController = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        onWindowClosed?()
    }

    func refreshAppearance() {
        webViewHost?.emitThemeChanged()
    }

    func setCollapsed(_ collapsed: Bool) {
        collapseController?.setCollapsed(collapsed)
    }

    nonisolated func windowWillClose(_ notification: Notification) {
        Task { @MainActor in
            dismiss()
        }
    }

    private func centerPanel(_ panel: NSWindow, size: NSSize) {
        let screenFrame = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let origin = NSPoint(
            x: screenFrame.midX - size.width / 2,
            y: screenFrame.midY - size.height / 2
        )
        panel.setFrame(NSRect(origin: origin, size: size), display: false)
    }
}
