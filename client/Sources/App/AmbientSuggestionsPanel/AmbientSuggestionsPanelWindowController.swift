import AppKit
import Foundation

@MainActor
final class AmbientSuggestionsPanelWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    private var webViewHost: AmbientSuggestionsPanelWebView?
    private var suggestions: [String: AmbientSuggestionRecord] = [:]
    private var localKeyMonitor: Any?
    private var collapseController: WindowCollapseController?

    private let initialPanelSize = NSSize(width: 392, height: 276)
    private let expandedMinSize = NSSize(width: 360, height: 220)
    private let defaultCollapsedSize = NSSize(width: 220, height: 64)

    var isVisible: Bool { panel != nil && (panel?.isVisible ?? false) }

    func orderFrontIfHidden() {
        if panel == nil {
            createPanel()
        }
        guard let panel else { return }
        if panel.isMiniaturized {
            panel.deminiaturize(nil)
        }
        if !panel.isVisible {
            panel.orderFront(nil)
        }
    }

    func hide() {
        panel?.orderOut(nil)
    }

    func upsertSuggestion(_ suggestion: AmbientSuggestionRecord) {
        suggestions[suggestion.suggestionId] = suggestion
        orderFrontIfHidden()
        webViewHost?.addSuggestion(suggestion)
    }

    func removeSuggestion(_ suggestionId: String) {
        suggestions.removeValue(forKey: suggestionId)
        webViewHost?.removeSuggestion(suggestionId)
    }

    func updateStatus(_ status: [String: Any]) {
        webViewHost?.sendStatusChanged(status)
    }

    private func createPanel() {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: initialPanelSize),
            styleMask: [.nonactivatingPanel, .borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        panel.title = "Proactive Suggestions"
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.worksWhenModal = true
        panel.isMovableByWindowBackground = true
        panel.delegate = self
        panel.minSize = expandedMinSize
        panel.contentMinSize = expandedMinSize

        let host = AmbientSuggestionsPanelWebView()
        self.webViewHost = host
        host.onAcceptSuggestion = { [weak self] suggestionId in
            self?.acceptSuggestion(suggestionId)
        }
        host.onRejectSuggestion = { [weak self] suggestionId in
            self?.rejectSuggestion(suggestionId)
        }
        host.onDismissPanel = { [weak self] in
            self?.hide()
        }
        host.onMinimizePanel = { [weak self] in
            self?.panel?.miniaturize(nil)
        }
        host.onToggleCollapsePanel = { [weak self] compactSize in
            self?.toggleCollapsed(compactSize: compactSize)
        }
        host.onRequestResize = { _, _ in }
        host.onRuntimeChanged = {
            Task { @MainActor in
                if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                    await appDelegate.statusBarManager?.refreshAmbientSuggestionState()
                }
                NotificationCenter.default.post(name: .ambientSuggestionsSettingsChanged, object: nil)
            }
        }

        host.webView.frame = NSRect(origin: .zero, size: panel.contentView?.bounds.size ?? initialPanelSize)
        host.webView.autoresizingMask = [.width, .height]
        panel.contentView = host.webView
        WebKitWindowChromeAppearance.apply(to: panel)
        host.installDragArea()
        host.loadContent()
        positionTopLeft(panel)
        setupWindowCommandShortcuts(for: panel)
        self.panel = panel
        collapseController = WindowCollapseController(
            window: panel,
            compactSize: defaultCollapsedSize,
            fallbackExpandedSize: initialPanelSize
        )
        AppearanceRefreshCoordinator.shared.register(self)
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    private func acceptSuggestion(_ suggestionId: String) {
        guard let suggestion = suggestions[suggestionId] else { return }
        AmbientSuggestionLaunchHelper.shared.launch(suggestion)
        removeSuggestion(suggestionId)
        Task {
            _ = try? await APIClient.shared.updateAmbientSuggestionOutcome(suggestionId: suggestionId, outcome: "accepted")
        }
    }

    private func rejectSuggestion(_ suggestionId: String) {
        removeSuggestion(suggestionId)
        Task {
            _ = try? await APIClient.shared.updateAmbientSuggestionOutcome(suggestionId: suggestionId, outcome: "rejected")
        }
    }

    private func toggleCollapsed(compactSize: NSSize?) {
        guard let collapseController else { return }
        collapseController.setCollapsed(
            !collapseController.isCollapsed,
            preferredCompactSize: compactSize
        )
    }

    private func positionTopLeft(_ panel: NSPanel) {
        guard let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        let margin: CGFloat = 16
        let origin = NSPoint(
            x: visible.minX + margin,
            y: visible.maxY - panel.frame.height - margin
        )
        panel.setFrameOrigin(origin)
    }

    private func setupWindowCommandShortcuts(for window: NSWindow) {
        cleanupWindowCommandShortcuts()
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self,
                  let panel = self.panel,
                  panel === window,
                  panel.isKeyWindow || panel.isMainWindow,
                  event.modifierFlags.contains(.command) else {
                return event
            }

            switch event.charactersIgnoringModifiers?.lowercased() {
            case "m":
                panel.miniaturize(nil)
                return nil
            case "w":
                self.hide()
                return nil
            default:
                return event
            }
        }
    }

    private func cleanupWindowCommandShortcuts() {
        if let localKeyMonitor {
            NSEvent.removeMonitor(localKeyMonitor)
            self.localKeyMonitor = nil
        }
    }

}
