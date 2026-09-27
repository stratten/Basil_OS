import AppKit

@MainActor
final class AudioFileUploadWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    private static var retainedInstance: AudioFileUploadWindowController?

    private var webView: AudioFileUploadWebView?
    private var bridgeController: AudioFileUploadBridgeController?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var collapseController: WindowCollapseController?

    private static let windowSize = NSSize(width: 600, height: 560)
    private static let minimumWindowSize = NSSize(width: 520, height: 480)
    private static let headerHeight: CGFloat = 44

    static func show() {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: windowSize.width, height: windowSize.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Upload Audio File"
        window.isReleasedWhenClosed = true
        window.isMovableByWindowBackground = true
        window.contentMinSize = minimumWindowSize
        window.contentMaxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        window.center()

        let controller = AudioFileUploadWindowController(window: window)
        window.delegate = controller
        retainedInstance = controller

        let viewModel = AudioFileUploadViewModel()
        let webView = AudioFileUploadWebView()
        controller.webView = webView
        window.contentView = webView.webView
        WebKitWindowChromeAppearance.apply(to: window)

        let dragView = WindowDragAreaView(leadingInteractiveWidth: 84, trailingInteractiveWidth: 0)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: WebKitWindowChromeAppearance.frameInset + headerHeight),
        ])

        controller.keyboardShortcuts = WindowKeyboardShortcuts(window: window)

        let collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: windowSize
        )
        controller.collapseController = collapseController

        let bridgeController = AudioFileUploadBridgeController(viewModel: viewModel, output: webView, window: window, collapseController: collapseController)
        controller.bridgeController = bridgeController
        webView.onIntent = { [weak bridgeController] intent in bridgeController?.handle(intent: intent) }
        webView.onReady = { [weak bridgeController] in bridgeController?.sendInitialSnapshot() }
        webView.loadContent()

        AppearanceRefreshCoordinator.shared.register(controller)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        #if DEBUG
        DevLogger.shared.info("📂 Audio file upload window displayed", context: "AudioFileUploadWindowController")
        #endif
    }

    func refreshAppearance() {
        bridgeController?.sendThemeChanged()
    }

    func windowWillClose(_ notification: Notification) {
        webView?.tearDown()
        webView = nil
        bridgeController = nil
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        collapseController = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        Self.retainedInstance = nil
    }
}
