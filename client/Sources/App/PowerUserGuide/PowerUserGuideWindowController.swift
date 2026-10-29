import AppKit
import SwiftUI

/// Window controller for the Power User Guide. Hosts a resizable,
/// custom-chrome `CustomBorderlessWindow` (matching the pattern used by
/// `BasilBoardWindowController`/`SettingsShellWindowController`) instead of a
/// plain titled `NSWindow`: a WKWebView-rendered React guide, with
/// `AppearanceRefreshCoordinator` registration for live theme updates and Cmd-W/
/// Cmd-M hotkeys. The window closes if the bundle fails to load rather than
/// remaining open and blank.
@MainActor
final class PowerUserGuideWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    static let shared = PowerUserGuideWindowController()

    private var window: NSWindow?
    private var webViewHost: PowerUserGuidePanelWebView?
    private var keyboardShortcuts: WindowKeyboardShortcuts?

    private static let windowSize = NSSize(width: 900, height: 700)
    private static let minimumWindowSize = NSSize(width: 760, height: 520)
    private static let headerHeight: CGFloat = 44

    var isVisible: Bool { window != nil && (window?.isVisible ?? false) }

    // MARK: - Public API

    func show() {
        guard window == nil else {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: Self.windowSize.width, height: Self.windowSize.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.configureCustomChromeWindow(title: "Basil's Capabilities", releasedWhenClosed: false)
        window.contentMinSize = Self.minimumWindowSize
        window.contentMaxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        window.delegate = self

        let targetScreen = NSApp.keyWindow?.screen ?? NSScreen.main
        if let screen = targetScreen {
            let screenFrame = screen.visibleFrame
            let size = window.frame.size
            window.setFrameOrigin(NSPoint(x: screenFrame.midX - size.width / 2, y: screenFrame.midY - size.height / 2))
        } else {
            window.center()
        }

        let webViewHost = PowerUserGuidePanelWebView()
        webViewHost.hotkeysPayload = PowerUserGuideHotkeys.payload(serviceBindings: HotkeyService.shared.hotkeyBindings)
        self.webViewHost = webViewHost
        webViewHost.onDismiss = { [weak self] in
            self?.dismiss()
        }
        webViewHost.onNavigationFailed = { [weak self] in
            #if DEBUG
            DevLogger.shared.error("PowerUserGuidePanelWebView navigation failed; closing guide window", context: "PowerUserGuide")
            #endif
            self?.dismiss()
        }
        window.contentView = webViewHost.webView
        WebKitWindowChromeAppearance.apply(to: window)

        let dragView = WindowDragAreaView(leadingInteractiveWidth: 0, trailingInteractiveWidth: 40)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webViewHost.webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webViewHost.webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webViewHost.webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webViewHost.webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: WebKitWindowChromeAppearance.frameInset + Self.headerHeight),
        ])

        keyboardShortcuts = WindowKeyboardShortcuts(window: window)

        self.window = window
        webViewHost.loadContent()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        AppearanceRefreshCoordinator.shared.register(self)
        startObservingHotkeys()

        #if DEBUG
        DevLogger.shared.info("PowerUserGuideWindowController shown", context: "PowerUserGuide")
        #endif
    }

    func dismiss() {
        guard let window else { return }
        window.close()
        cleanup()

        #if DEBUG
        DevLogger.shared.info("PowerUserGuideWindowController dismissed", context: "PowerUserGuide")
        #endif
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    // MARK: - Hotkeys

    /// The guide names the user's real hotkeys, so it re-reads them when Settings changes one and once right after opening, in case the hotkey service's own copy was stale.
    private func startObservingHotkeys() {
        for name in ["HotkeyStateChanged", "HotkeyBindingsChanged"] {
            NotificationCenter.default.addObserver(self, selector: #selector(hotkeysMayHaveChanged), name: NSNotification.Name(name), object: nil)
        }
        hotkeysMayHaveChanged()
    }

    private func stopObservingHotkeys() {
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("HotkeyStateChanged"), object: nil)
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("HotkeyBindingsChanged"), object: nil)
    }

    @objc private func hotkeysMayHaveChanged() {
        Task { @MainActor [weak self] in
            guard let payload = await PowerUserGuideHotkeys.fetchPayload() else { return }
            guard let self, let webViewHost = self.webViewHost else { return }
            webViewHost.hotkeysPayload = payload
            webViewHost.sendHotkeysChanged()
        }
    }

    // MARK: - Private

    private func cleanup() {
        stopObservingHotkeys()
        webViewHost?.tearDown()
        webViewHost = nil
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        window?.delegate = nil
        window = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
    }

    // MARK: - NSWindowDelegate

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        dismiss()
        return false
    }

    deinit {
        MainActor.assumeIsolated {
            AppearanceRefreshCoordinator.shared.unregister(self)
        }
        #if DEBUG
        DevLogger.shared.info("PowerUserGuideWindowController deinit", context: "PowerUserGuide")
        #endif
    }
}
