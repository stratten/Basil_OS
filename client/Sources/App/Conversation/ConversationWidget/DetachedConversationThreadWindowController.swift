import AppKit

@MainActor
final class DetachedConversationThreadWindowController: NSObject, NSWindowDelegate {
    private let conversationId: String
    private let initialFrame: NSRect
    private let onDismiss: (String) -> Void
    private var window: NSWindow?
    private var host: BasilBoardWebView?
    private var collapseController: WindowCollapseController?
    private var keyboardShortcuts: WindowKeyboardShortcuts?

    init(conversationId: String, initialFrame: NSRect, onDismiss: @escaping (String) -> Void) {
        self.conversationId = conversationId
        self.initialFrame = initialFrame
        self.onDismiss = onDismiss
    }

    func show() {
        let window = CustomBorderlessWindow(
            contentRect: initialFrame,
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Conversation"
        window.isReleasedWhenClosed = false
        // Matches every other detached document-style window in the app
        // (e.g. DetachedAgentTaskWindowController): without `.floating`, this
        // window sits at the default level and renders behind the other
        // (floating) Basil windows, appearing stuck-behind and unclickable.
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        window.hidesOnDeactivate = false
        window.isMovableByWindowBackground = true
        window.minSize = NSSize(width: 400, height: 300)
        window.delegate = self

        let host = BasilBoardWebView(
            entryPage: .conversation,
            initialConversationId: conversationId,
            conversationPresentation: .thread
        )
        host.hostWindow = window
        host.onClose = { [weak self] in self?.dismiss() }
        host.onMinimize = { [weak window] in window?.miniaturize(nil) }
        host.onCollapseRequested = { [weak self] in self?.collapseController?.setCollapsed(true) }
        host.onExpandRequested = { [weak self] in self?.collapseController?.setCollapsed(false) }
        window.contentView = host.webView
        WebKitWindowChromeAppearance.apply(to: window)
        host.installDragArea()

        self.window = window
        self.host = host
        keyboardShortcuts = WindowKeyboardShortcuts(window: window)
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: initialFrame.size
        )
        host.loadContent()
        // Deliberately does NOT acquire a `ConversationPresentationCoordinator`
        // standalone lease: that coarse lease hides the Board's entire Chats
        // tab, which is the right behavior for the legacy single global
        // Conversation widget (`ConversationWindowController`, which isn't
        // scoped to one conversation) but wrong here, since a per-thread
        // window like this one should only affect the display of its own
        // specific conversation. `DetachedConversationThreadWindowManager`'s
        // `onDetachedConversationsChanged` callback handles that fine-grained
        // per-conversation coordination instead.
        window.makeKeyAndOrderFront(nil)
    }

    func bringToFront() {
        if window?.isMiniaturized == true {
            window?.deminiaturize(nil)
        }
        window?.makeKeyAndOrderFront(nil)
    }

    func windowWillClose(_ notification: Notification) {
        dismiss()
    }

    private func dismiss() {
        guard window != nil else { return }
        window?.delegate = nil
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        window?.orderOut(nil)
        window = nil
        host?.tearDown()
        host = nil
        collapseController = nil
        onDismiss(conversationId)
    }
}
