import AppKit

// MARK: - Window Controller
@MainActor
final class ConversationWindowController: NSObject, NSWindowDelegate {
    private var panel: NSWindow?
    private var webViewHost: BasilBoardWebView?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    // Collapse-to-chrome bookkeeping, delegated to the shared
    // `WindowCollapseController`. `collapseController.isCollapsed` suppresses
    // size persistence so the slim strip never overwrites the saved full
    // window size.
    private var collapseController: WindowCollapseController?
    /// Height of the collapsed header strip (close/minimize/collapse + title).
    private let collapsedHeaderHeight: CGFloat = 64
    /// Width needed for the collapsed chrome controls and truncated title.
    private let collapsedHeaderWidth: CGFloat = 300
    private let defaultWindowSize = NSSize(width: 700, height: 600)

    var isVisible: Bool { panel != nil && panel!.isVisible }

    func show() {
        show(conversationId: nil)
    }

    func show(conversationId: String?) {
        guard panel == nil else {
            // If panel exists, just make it visible and front
            if panel?.isMiniaturized == true {
                panel?.deminiaturize(nil)
            }
            NSApp.activate(ignoringOtherApps: true)
            panel?.makeKeyAndOrderFront(nil)
            ConversationPresentationCoordinator.shared.standaloneDidBecomeVisible()
            navigateToConversation(conversationId)
            webViewHost?.focusConversationComposer()
            return
        }

        // Load saved settings SYNCHRONOUSLY before creating window
        var initialSize = defaultWindowSize
        let settings = APIClient.shared.getCachedConversationWidgetSettings()

        if let savedSize = settings.widgetSize {
            initialSize = NSSize(width: savedSize.width, height: savedSize.height)
            print("📏 Restoring saved conversation widget size: \(initialSize.width) x \(initialSize.height)")
        }

        // Create window using CustomBorderlessWindow for proper text input support
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: initialSize.width, height: initialSize.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        // Configure window behavior
        window.title = "Conversation"
        window.level = .floating
        window.collectionBehavior = [
            .canJoinAllSpaces,     // Show on all spaces
            .fullScreenAuxiliary,   // Proper fullscreen behavior
            .stationary,            // Don't move when switching spaces
            .ignoresCycle           // Don't include in window cycling
        ]

        // Modern window behavior settings
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true // Allow dragging by background

        // Set up delegate to track window changes
        window.delegate = self

        // Set minimum size constraints
        window.minSize = NSSize(width: 400, height: 500)

        let host = BasilBoardWebView(entryPage: .conversation)
        host.hostWindow = window
        host.onClose = { [weak self] in self?.hide() }
        host.onMinimize = { [weak self] in self?.minimize() }
        host.onCollapseRequested = { [weak self] in self?.setCollapsed(true) }
        host.onExpandRequested = { [weak self] in self?.setCollapsed(false) }
        host.onReady = { [weak host] in
            guard let host else { return }
            fadeInWebViewContent(host.webView)
        }

        host.webView.frame = NSRect(origin: .zero, size: initialSize)
        host.webView.autoresizingMask = [.width, .height] // Enable autoresizing
        host.webView.alphaValue = 0

        window.contentView = host.webView

        WebKitWindowChromeAppearance.apply(to: window)
        host.installDragArea()
        host.loadContent()

        self.panel = window
        self.webViewHost = host

        // Restore saved position or center
        var positioned = false
        if let positionData = settings.widgetPosition {
            let x = positionData.x
            let y = positionData.y
            let screenID = positionData.screenID
            let screens = NSScreen.screens
            let targetScreen = screens.first { screen in
                if let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
                    return id.intValue == screenID
                }
                return false
            } ?? NSScreen.main
            if let visibleFrame = targetScreen?.visibleFrame {
                let posX = min(max(CGFloat(x), visibleFrame.minX), visibleFrame.maxX - window.frame.width)
                let posY = min(max(CGFloat(y), visibleFrame.minY), visibleFrame.maxY - window.frame.height)
                window.setFrameOrigin(NSPoint(x: posX, y: posY))
                print("📍 Restoring saved conversation widget position: \(posX), \(posY) on screen \(screenID)")
                positioned = true
            }
        }
        if !positioned {
            window.center()
        }

        // Set up keyboard shortcuts (Cmd+W to close, Cmd+M to minimize)
        keyboardShortcuts = WindowKeyboardShortcuts(window: window)
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: collapsedHeaderWidth, height: collapsedHeaderHeight),
            fallbackExpandedSize: defaultWindowSize
        )

        // Make the window visible and key for text input
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        host.focusConversationComposer()
        ConversationPresentationCoordinator.shared.standaloneDidBecomeVisible()
        navigateToConversation(conversationId)

        // Load settings from backend asynchronously
        Task {
            do {
                let fetchedSettings = try await APIClient.shared.getConversationWidgetSettings()
                APIClient.shared.cacheConversationWidgetSettings(fetchedSettings)
                #if DEBUG
                DevLogger.shared.info("✅ Loaded conversation widget settings from backend", context: "ConversationWidget")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Failed to load conversation widget settings: \(error)", context: "ConversationWidget")
                #endif
            }
        }
    }

    private func navigateToConversation(_ conversationId: String?) {
        guard let conversationId,
              !conversationId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        _ = webViewHost?.navigateToAgentTaskOrigin(
            originType: "conversation",
            originId: conversationId
        )
    }

    func hide() {
        guard let panel = panel else { return }
        panel.orderOut(nil)
        ConversationPresentationCoordinator.shared.standaloneDidDismiss()

        // Don't release resources, just hide the window
    }

    func minimize() {
        guard let panel = panel else { return }
        panel.miniaturize(nil)
    }

    /// Collapse the window to its header strip (top-anchored) or expand it back
    /// to the saved height. Width is preserved either way. Size persistence is
    /// suppressed while collapsed so the strip height never overwrites the saved
    /// full window size.
    func setCollapsed(_ collapsed: Bool) {
        collapseController?.setCollapsed(collapsed)
    }

    func toggle() {
        if panel?.isMiniaturized == true {
            show()
            return
        }
        if isVisible && NSApp.isActive && panel?.isKeyWindow == true {
            hide()
        } else {
            show()
        }
    }

    // MARK: - NSWindowDelegate
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // Just hide the window instead of closing it
        hide()
        return false
    }

    func windowWillClose(_ notification: Notification) {
        ConversationPresentationCoordinator.shared.standaloneDidDismiss()

        guard let closingWindow = notification.object as? NSWindow,
              closingWindow === panel else { return }

        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        webViewHost?.tearDown()
        webViewHost = nil
        panel = nil
        collapseController = nil
    }

    func windowDidMiniaturize(_ notification: Notification) {
        ConversationPresentationCoordinator.shared.standaloneDidDismiss()
    }

    func windowDidDeminiaturize(_ notification: Notification) {
        ConversationPresentationCoordinator.shared.standaloneDidBecomeVisible()
    }

    func windowDidResize(_ notification: Notification) {
        // Debounce the save operation
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(saveWindowSize), object: nil)
        perform(#selector(saveWindowSize), with: nil, afterDelay: 0.5)
    }

    func windowDidMove(_ notification: Notification) {
        // Debounce the save operation
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(saveWindowPosition), object: nil)
        perform(#selector(saveWindowPosition), with: nil, afterDelay: 0.5)
    }

    @objc private func saveWindowSize() {
        // Never persist the collapsed strip height; it would shrink the window
        // permanently on the next launch.
        guard collapseController?.isCollapsed != true else { return }
        guard let size = panel?.frame.size else { return }
        #if DEBUG
        DevLogger.shared.info("💾 Saving conversation widget size: \(size.width) x \(size.height)", context: "ConversationWidget")
        #endif

        Task {
            do {
                // Refresh settings before saving
                do {
                    let data = try await APIClient.shared.get("/settings/conversation-widget")
                    if let response = try? JSONDecoder().decode(ConversationWidgetSettingsResponse.self, from: data) {
                        APIClient.shared.cacheConversationWidgetSettings(response.settings)
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to refresh settings before saving size: \(error)", context: "ConversationWidget")
                    #endif
                }

                try await APIClient.shared.updateConversationWidgetSize(size)
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Failed to save conversation widget size: \(error)", context: "ConversationWidget")
                #endif
            }
        }
    }

    @objc private func saveWindowPosition() {
        guard let window = panel,
              let screen = window.screen else { return }

        let position = window.frame.origin
        var screenID = 0
        if let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
            screenID = id.intValue
        }

        #if DEBUG
        DevLogger.shared.info("💾 Saving conversation widget position: (\(position.x), \(position.y)) on screen \(screenID)", context: "ConversationWidget")
        #endif

        Task {
            do {
                // Refresh settings before saving
                do {
                    let data = try await APIClient.shared.get("/settings/conversation-widget")
                    if let response = try? JSONDecoder().decode(ConversationWidgetSettingsResponse.self, from: data) {
                        APIClient.shared.cacheConversationWidgetSettings(response.settings)
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to refresh settings before saving position: \(error)", context: "ConversationWidget")
                    #endif
                }

                try await APIClient.shared.updateConversationWidgetPosition(position, screenID: screenID)
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Failed to save conversation widget position: \(error)", context: "ConversationWidget")
                #endif
            }
        }
    }

    deinit {
        #if DEBUG
        DevLogger.shared.info("ConversationWindowController deinit", context: "ConversationWidget")
        #endif
    }
}

// MARK: - Manager
@MainActor
final class ConversationWidgetManager {
    // MARK: - Singleton
    static let shared = ConversationWidgetManager()

    // MARK: - Properties
    private var windowController: ConversationWindowController?

    // MARK: - Initialization
    private init() {
        #if DEBUG
        DevLogger.shared.info("ConversationWidgetManager initialized", context: "ConversationWidget")
        #endif
    }

    deinit {
        #if DEBUG
        DevLogger.shared.info("ConversationWidgetManager deinit", context: "ConversationWidget")
        #endif
    }

    // MARK: - Public Methods
    /// Shows the conversation widget
    func show() {
        show(conversationId: nil)
    }

    func show(conversationId: String?) {
        // Pre-load settings before showing window
        Task {
            do {
                let settings = try await APIClient.shared.getConversationWidgetSettings()
                APIClient.shared.cacheConversationWidgetSettings(settings)
                #if DEBUG
                DevLogger.shared.info("✅ Pre-loaded conversation widget settings", context: "ConversationWidget")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("⚠️ Failed to pre-load settings, using defaults: \(error)", context: "ConversationWidget")
                #endif
            }

            await MainActor.run {
                ensureWindowController().show(conversationId: conversationId)
            }
        }
    }

    /// Hides the conversation widget
    func hide() {
        windowController?.hide()
    }

    /// Minimizes the conversation widget to the dock
    func minimize() {
        windowController?.minimize()
    }

    /// Collapses the conversation widget to its header strip, or expands it.
    func toggleCollapse(_ collapsed: Bool) {
        windowController?.setCollapsed(collapsed)
    }

    /// Toggles the conversation widget visibility
    func toggle() {
        ensureWindowController().toggle()
    }

    // MARK: - Private Methods
    private func ensureWindowController() -> ConversationWindowController {
        if windowController == nil {
            windowController = ConversationWindowController()
        }
        return windowController!
    }
}
