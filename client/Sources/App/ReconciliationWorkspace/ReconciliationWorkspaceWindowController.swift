import SwiftUI
import AppKit

/// Borderless workspace window styled to match the Agent Task Result widget:
/// transparent native stack (hasShadow=false / isOpaque=false / clear
/// background), aqua appearance so the light-mode tokens render correctly, a
/// clear content layer, and a top drag strip installed by the webview. Uses the
/// default window level and centers on show (a Settings-launched workspace, not
/// a floating HUD).
@MainActor
final class ReconciliationWorkspaceWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    private var completion: (() -> Void)?
    private var didComplete = false
    private let closeRelay = ReconciliationCloseRelay()
    // Collapse-to-chrome bookkeeping, delegated to the shared
    // `WindowCollapseController`, matching every other collapsible React
    // window in this app (Settings, Conversation, BasilBoard, etc.).
    private var collapseController: WindowCollapseController?
    private weak var reconciliationCoordinator: ReconciliationWorkspaceWebView.Coordinator?

    init(completion: (() -> Void)?) {
        self.completion = completion
        let relay = closeRelay
        let hostingView = NSHostingView(rootView: AnyView(EmptyView()))
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 920, height: 660),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Skill Reconciliation"
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true
        window.minSize = NSSize(width: 740, height: 520)
        window.contentView = hostingView
        WebKitWindowChromeAppearance.apply(to: window)
        window.center()
        super.init(window: window)

        let contentView = ReconciliationWorkspaceWebView(
            onClose: { [weak relay] in relay?.close() },
            onMinimize: { [weak relay] in relay?.minimize() },
            onCollapse: { [weak relay] in relay?.collapse() },
            onExpand: { [weak relay] in relay?.expand() },
            onCoordinatorReady: { [weak self] coordinator in
                self?.reconciliationCoordinator = coordinator
                if let self {
                    AppearanceRefreshCoordinator.shared.register(self)
                }
            }
        )
        hostingView.rootView = AnyView(contentView)
        window.delegate = self
        closeRelay.onClose = { [weak self] in self?.finish() }
        closeRelay.onMinimize = { [weak window] in window?.miniaturize(nil) }
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 920, height: 660)
        )
        closeRelay.onCollapse = { [weak self] in self?.collapseController?.setCollapsed(true) }
        closeRelay.onExpand = { [weak self] in self?.collapseController?.setCollapsed(false) }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func show() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func focus() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        finish()
    }

    func refreshAppearance() {
        reconciliationCoordinator?.sendThemeChanged()
    }

    private func finish() {
        if didComplete { return }
        didComplete = true
        completion?()
        completion = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        window?.close()
    }
}

private final class ReconciliationCloseRelay {
    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onCollapse: (() -> Void)?
    var onExpand: (() -> Void)?

    func close() {
        onClose?()
    }

    func minimize() {
        onMinimize?()
    }

    func collapse() {
        onCollapse?()
    }

    func expand() {
        onExpand?()
    }
}
