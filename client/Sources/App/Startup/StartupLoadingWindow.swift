import AppKit
import Foundation

@MainActor
final class StartupLoadingWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    var viewModel: StartupLoadingViewModel?
    private var webViewHost: StartupLoadingWebView?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var collapseController: WindowCollapseController?
    private var didHide = false

    private static let windowSize = NSSize(width: 400, height: 188)
    private static let compactSize = NSSize(width: 400, height: 64)
    private static let headerHeight: CGFloat = 44

    init() {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(origin: .zero, size: Self.windowSize),
            styleMask: [.borderless, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.configureCustomChromeWindow(title: "Basil", releasedWhenClosed: false)
        window.level = .floating
        window.center()

        super.init(window: window)
        window.delegate = self

        let viewModel = StartupLoadingViewModel()
        self.viewModel = viewModel

        let webViewHost = StartupLoadingWebView()
        self.webViewHost = webViewHost
        webViewHost.onDrawnIn = { [weak self] in
            self?.viewModel?.markDrawnIn()
        }
        webViewHost.onClose = { [weak self] in
            self?.viewModel?.complete(immediately: true)
        }
        webViewHost.onMinimize = { [weak self] in
            self?.window?.miniaturize(nil)
        }
        webViewHost.onCollapse = { [weak self] in
            self?.collapseController?.setCollapsed(true)
        }
        webViewHost.onExpand = { [weak self] in
            self?.collapseController?.setCollapsed(false)
        }
        webViewHost.onNavigationFailed = {
            #if DEBUG
            DevLogger.shared.error("StartupLoadingWebView navigation failed", context: "StartupLoadingWindow")
            #endif
        }
        window.contentView = webViewHost.webView
        WebKitWindowChromeAppearance.apply(to: window)

        let dragView = WindowDragAreaView(leadingInteractiveWidth: 84, trailingInteractiveWidth: 0)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webViewHost.webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webViewHost.webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webViewHost.webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webViewHost.webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: WebKitWindowChromeAppearance.frameInset + Self.headerHeight),
        ])

        keyboardShortcuts = WindowKeyboardShortcuts(window: window)
        collapseController = WindowCollapseController(
            window: window,
            compactSize: Self.compactSize,
            fallbackExpandedSize: Self.windowSize
        )

        viewModel.onStatusChange { [weak self] message in
            self?.webViewHost?.sendStatus(message)
        }
        viewModel.startMonitoring()
        webViewHost.loadContent(message: viewModel.currentMessage)
        AppearanceRefreshCoordinator.shared.register(self)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        #if DEBUG
        DevLogger.shared.info("Startup loading window created and displayed", context: "StartupLoadingWindow")
        #endif
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func hideWindow() {
        guard !didHide else { return }
        didHide = true
        viewModel?.stopMonitoring()
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        collapseController = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        webViewHost?.tearDown()
        webViewHost = nil
        window?.orderOut(nil)

        #if DEBUG
        DevLogger.shared.info("Startup loading window hidden", context: "StartupLoadingWindow")
        #endif
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        viewModel?.complete(immediately: true)
        return false
    }
}
