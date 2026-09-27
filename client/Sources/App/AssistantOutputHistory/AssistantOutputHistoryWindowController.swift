import AppKit

/// Singleton window controller hosting the React AssistantSession history surface.
final class AssistantOutputHistoryWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    static var sharedController: AssistantOutputHistoryWindowController?

    private static let expandedMinSize = NSSize(width: 500, height: 350)
    private static let collapsedWidth: CGFloat = 300
    private static let collapsedHeight: CGFloat = 64

    private let viewModel: AssistantOutputHistoryViewModel
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var collapseController: WindowCollapseController?
    fileprivate var webView: AssistantOutputHistoryWebView?

    init(window: NSWindow, viewModel: AssistantOutputHistoryViewModel) {
        self.viewModel = viewModel
        super.init(window: window)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleHistoryDidUpdate(_:)),
            name: NSNotification.Name("AssistantOutputHistoryDidUpdate"),
            object: nil
        )
        AppearanceRefreshCoordinator.shared.register(self)
    }

    @objc private func handleHistoryDidUpdate(_ notification: Notification) {
        webView?.sendHistoryUpdated()
    }

    func refreshAppearance() {
        webView?.sendThemeChanged(theme: AssistantSessionThemeSnapshot.currentJSON())
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    // MARK: - Show

    static func show(anchorFrame: NSRect? = nil) {
        if let existing = sharedController {
            if existing.window?.isMiniaturized == true {
                existing.window?.deminiaturize(nil)
            }
            existing.window?.orderFront(nil)
            return
        }

        let viewModel = AssistantOutputHistoryViewModel()
        let webView = AssistantOutputHistoryWebView()

        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 700, height: 500),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.level = .floating
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]
        window.hidesOnDeactivate = false
        window.hasShadow = false
        window.alphaValue = 1.0
        window.isOpaque = false
        window.title = "Dill - Assistant History"
        window.backgroundColor = NSColor.clear
        window.isMovableByWindowBackground = true
        window.contentView = webView.webView
        window.minSize = Self.expandedMinSize

        let controller = AssistantOutputHistoryWindowController(window: window, viewModel: viewModel)
        controller.webView = webView
        sharedController = controller
        window.delegate = controller

        webView.onClose = { [weak window] in window?.close() }
        webView.onMinimize = { [weak window] in window?.miniaturize(nil) }
        webView.onToggleChromeCollapse = { [weak controller] collapsed in
            controller?.setChromeCollapsed(collapsed)
        }
        webView.onRefineFromHistory = { [weak controller] assistantOutputId in
            controller?.rehydrateAndShowWidget(assistantOutputId: assistantOutputId)
        }
        webView.onReady = { [weak webView] in
            webView?.sendInit(
                baseUrl: APIClient.shared.baseURL,
                anchoredToWidget: anchorFrame != nil,
                theme: AssistantSessionThemeSnapshot.currentJSON()
            )
        }
        webView.installDragArea()
        webView.loadContent()

        controller.setupBorderlessAppearance(for: window)
        controller.keyboardShortcuts = WindowKeyboardShortcuts(window: window)
        controller.collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: Self.collapsedWidth, height: Self.collapsedHeight),
            fallbackExpandedSize: NSSize(width: 700, height: 500)
        )

        window.setFrameOrigin(Self.positionedOrigin(for: window.frame, anchorFrame: anchorFrame))

        window.orderFront(nil)

        #if DEBUG
        DevLogger.shared.info("🪟 AssistantOutputHistoryWindowController shown", context: "AssistantOutputHistoryWindowController")
        #endif
    }

    func rehydrateAndShowWidget(assistantOutputId: Int) {
        Task { @MainActor in
            viewModel.errorMessage = nil
            await viewModel.resumeRefinement(id: assistantOutputId, outputType: "assistant_session")
            if let errorMessage = viewModel.errorMessage {
                webView?.sendHistoryActionError(errorMessage)
            }
        }
    }

    func setChromeCollapsed(_ collapsed: Bool) {
        collapseController?.setCollapsed(collapsed)
    }

    // MARK: - NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        if AssistantOutputHistoryWindowController.sharedController === self {
            AssistantOutputHistoryWindowController.sharedController = nil
        }
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
        AppearanceRefreshCoordinator.shared.unregister(self)
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil

        #if DEBUG
        DevLogger.shared.info("🪟 AssistantOutputHistoryWindowController closed", context: "AssistantOutputHistoryWindowController")
        #endif
    }

    // MARK: - Private

    private static func positionedOrigin(for windowFrame: NSRect, anchorFrame: NSRect?) -> NSPoint {
        if let anchorFrame {
            let interPanelGap: CGFloat = 12
            return NSPoint(
                x: anchorFrame.minX - interPanelGap - windowFrame.width,
                y: anchorFrame.maxY - windowFrame.height
            )
        }

        if let screen = NSScreen.main {
            let screenFrame = screen.visibleFrame
            return NSPoint(
                x: screenFrame.midX - windowFrame.width / 2,
                y: screenFrame.midY - windowFrame.height / 2
            )
        }

        return windowFrame.origin
    }

    private func setupBorderlessAppearance(for window: NSWindow) {
        window.backgroundColor = .clear
        window.hasShadow = false
        window.isOpaque = false

        if let contentView = window.contentView {
            contentView.wantsLayer = true
            contentView.layer?.cornerRadius = 16
            contentView.layer?.masksToBounds = false
        }
    }
}
