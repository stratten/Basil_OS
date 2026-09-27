import AppKit
import SwiftUI
import Combine

/// Window controller for the floating "scheduled runs in flight" mini panel.
///
/// Mirrors ``ModelDownloadWindowController`` in spirit: a small, non-activating
/// borderless NSPanel that floats over other windows and never steals focus.
/// The actual UI is rendered inside a WKWebView (so the same React bundle
/// can later move to other host shells), wrapped here in a Swift-managed
/// panel so we can drive show/hide from native event sources (WS, AppDelegate).
///
/// Show/hide policy:
///   * ``orderFrontIfHidden()`` is the public hand-off the AppDelegate calls
///     when a ``scheduled_agent_task_run_started`` event arrives — it brings the
///     panel up the first time without forcing a re-show on every event.
///   * The panel hides itself in response to the React side reporting
///     ``panelEmpty`` (after a short coalesce window) or to an explicit user
///     dismiss. Either way we keep the WKWebView alive on hide so the next
///     ``orderFrontIfHidden`` is instantaneous and any in-flight WS rows
///     re-render immediately rather than after a fresh hydrate fetch.
@MainActor
final class ScheduledRunMiniPanelWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    private var webViewHost: ScheduledRunMiniPanelWebView?
    private var cancellables = Set<AnyCancellable>()
    /// Holds the local key-monitor token installed by
    /// ``setupWindowCommandShortcuts`` so we can remove it in
    /// ``cleanupWindowCommandShortcuts`` / ``deinit``. Mirrors the
    /// equivalent property on ``AgentTaskCaptureWindowController``.
    private var localKeyMonitor: Any?

    /// The React content size excludes the shared frame inset; the host adds that inset on every edge so the CSS rings remain inside the WKWebView.
    private let chromeInset = WebKitWindowChromeAppearance.frameInset

    /// Default size on first show; the React side will subsequently drive
    /// height via the requestResize bridge as the row count changes.
    /// Width 320 / height 84 are the *content* dimensions agreed with
    /// the React side; we expand by the shadow padding on both axes so
    /// the box-shadow halo is visible.
    private let initialContentSize = NSSize(width: 320, height: 84)
    private let collapsedHiddenContentSize = NSSize(width: 320, height: 84)

    private var initialSize: NSSize {
        NSSize(
            width: initialContentSize.width + chromeInset * 2,
            height: initialContentSize.height + chromeInset * 2
        )
    }

    /// Called when the user clicks a row to jump to the matching agent task in
    /// the persistent result/history widget. The AppDelegate wires this
    /// through to ``AgentTaskResultWidgetController/showExistingAgentTask(agentTaskId:anchorFrame:)``,
    /// which surfaces the singleton (creating it if necessary) and
    /// focuses the requested agent task. The capture widget is no longer
    /// involved in this path — it owns only ephemeral new-AgentTask
    /// captures.
    var onOpenAgentTask: ((_ agentTaskId: String, _ runId: String) -> Void)?

    var isVisible: Bool { panel != nil && (panel?.isVisible ?? false) }

    // MARK: - Public API

    /// Bring the panel forward if it isn't already visible. Idempotent. Use
    /// this from event sources that may fire multiple times for the same
    /// "show me what's running" intent (e.g. a burst of ``run_started`` WS
    /// events) — only the first one will materialize the panel; the rest
    /// no-op.
    func orderFrontIfHidden() {
        if panel == nil {
            createPanel()
        }
        guard let panel = panel else { return }
        if !panel.isVisible {
            positionBottomRight(panel)
            panel.alphaValue = 0
            panel.orderFront(nil)
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.18
                panel.animator().alphaValue = 1
            }
        }
    }

    /// Hide the panel (without tearing down the WKWebView). The React app
    /// continues to receive WS events while hidden so re-show is instant
    /// and shows the up-to-date row set.
    func hide() {
        guard let panel = panel else { return }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.18
            panel.animator().alphaValue = 0
        }, completionHandler: {
            panel.orderOut(nil)
        })
    }

    /// Push a fresh theme to the WKWebView (called from settings observers).
    func notifyThemeChanged() {
        webViewHost?.sendThemeChanged()
    }

    func refreshAppearance() {
        notifyThemeChanged()
    }

    // MARK: - Private

    private func createPanel() {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: initialSize),
            // ``.miniaturizable`` is required for ``miniaturize(nil)``
            // to actually park the panel in the Dock -- without it,
            // AppKit silently no-ops the call. We don't get a visible
            // minimize button from the style mask alone because we
            // also pass ``.borderless`` (no title bar to host the
            // traffic-light controls), but our React header surfaces
            // a custom button that posts a ``minimizePanel`` bridge
            // message; Swift forwards that to ``panel.miniaturize``
            // through the ``onMinimizePanel`` closure wired below.
            styleMask: [.nonactivatingPanel, .borderless, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        panel.title = "Scheduled Runs"
        panel.level = .floating
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
            .ignoresCycle,
        ]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.worksWhenModal = true
        panel.hasShadow = false
        panel.alphaValue = 1.0
        panel.isOpaque = false
        panel.backgroundColor = NSColor.clear
        panel.isMovableByWindowBackground = true
        panel.delegate = self

        let host = ScheduledRunMiniPanelWebView()
        self.webViewHost = host

        host.onOpenAgentTask = { [weak self] agentTaskId, runId in
            self?.onOpenAgentTask?(agentTaskId, runId)
        }

        host.onDismissRow = { _ in
            // Row-level dismiss is purely client-side in the React app today
            // (it removes the row from its in-memory list). We keep the
            // closure registered so we can later wire a backend "ignore this
            // run" if we want to. No-op for now.
        }

        host.onDismissPanel = { [weak self] in
            self?.hide()
        }

        host.onMinimizePanel = { [weak self] in
            // The React header's minimize button posts a
            // ``minimizePanel`` bridge message that fans out to this
            // closure. We send the panel to the Dock via the standard
            // AppKit API; clicking the Dock tile restores it. The
            // panel state (rows, websocket connection inside the
            // WKWebView) survives miniaturization because the panel
            // isn't ordered out -- only minimized.
            self?.panel?.miniaturize(nil)
        }

        host.onPanelEmpty = { [weak self] in
            self?.hide()
        }

        host.onRequestResize = { [weak self] width, height in
            self?.resize(to: NSSize(width: width, height: height))
        }

        panel.contentView = host.webView
        WebKitWindowChromeAppearance.apply(to: panel)

        // Make the panel draggable. NSPanel.isMovableByWindowBackground
        // is set above but does nothing on its own here because the
        // WKWebView swallows mouse events; the drag area subview is
        // what actually promotes a click in the header strip into a
        // window drag (mirrors AgentTaskResultWebView).
        host.installDragArea()

        positionBottomRight(panel)
        self.panel = panel
        AppearanceRefreshCoordinator.shared.register(self)

        // Install Cmd+M / Cmd+W shortcuts so the panel mirrors the
        // capture widget's window-controls semantics even though
        // ``.borderless`` means we don't get the standard
        // traffic-light buttons. Must be called after ``self.panel``
        // is assigned because the monitor closure captures
        // ``self.panel`` and identity-checks it on each event.
        setupWindowCommandShortcuts(for: panel)

        // Kick off content load. The webview's didFinish handler will fire
        // sendInit once the bundle is ready.
        host.loadContent()
    }

    // MARK: - Window Command Shortcuts (Cmd+M / Cmd+W)
    //
    // Mirrors ``AgentTaskCaptureWindowController.setupWindowCommandShortcuts``
    // so the two panels share keyboard semantics: Cmd+M sends the
    // panel to the Dock, Cmd+W hides it without destroying state.
    // We only respond when this controller's panel is actually the
    // key (or main) window so the monitor doesn't swallow Cmd+M /
    // Cmd+W intended for other windows in the app.

    private func setupWindowCommandShortcuts(for window: NSWindow) {
        cleanupWindowCommandShortcuts()
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self,
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
                // Mirrors the dismiss button: hide the panel without
                // tearing down the WKWebView so the next show is
                // instant. ``hide`` is the same routine used by the
                // onDismissPanel / onPanelEmpty closures, keeping
                // user-driven and event-driven hide paths consistent.
                self.hide()
                return nil
            default:
                return event
            }
        }
    }

    private func cleanupWindowCommandShortcuts() {
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }
    }

    private func positionBottomRight(_ panel: NSPanel) {
        let mouseLocation = NSEvent.mouseLocation
        let targetScreen = NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) } ?? NSScreen.main

        guard let screen = targetScreen else {
            panel.center()
            return
        }

        let visibleFrame = screen.visibleFrame
        let panelSize = panel.frame.size
        let padding: CGFloat = 16

        let originX = visibleFrame.maxX - panelSize.width - padding
        let originY = visibleFrame.origin.y + padding
        panel.setFrameOrigin(NSPoint(x: originX, y: originY))
    }

    private func resize(to newSize: NSSize) {
        guard let panel = panel else { return }
        let currentFrame = panel.frame
        // The React side reports content size only; Swift adds the shared frame inset on every edge so the CSS rings stay inside the WKWebView.
        let paddedSize = NSSize(
            width: newSize.width + chromeInset * 2,
            height: newSize.height + chromeInset * 2
        )
        // Keep the bottom-right anchor stable as height changes so the panel
        // appears to grow upward instead of dancing across the screen.
        let newOriginY = currentFrame.origin.y
        let newOriginX = currentFrame.origin.x + (currentFrame.width - paddedSize.width)
        let newFrame = NSRect(origin: NSPoint(x: newOriginX, y: newOriginY), size: paddedSize)
        if panel.isVisible {
            panel.setFrame(newFrame, display: true, animate: true)
        } else {
            panel.setFrame(newFrame, display: false)
        }
    }

    // MARK: - NSWindowDelegate

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hide()
        return false
    }

    deinit {
        cancellables.removeAll()
        MainActor.assumeIsolated {
            AppearanceRefreshCoordinator.shared.unregister(self)
        }
        // Remove the local key monitor synchronously on dealloc so we
        // don't leak it across controller lifecycles. ``cleanup`` is
        // safe to call regardless of whether we ever installed a
        // monitor (it null-checks internally).
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }
        #if DEBUG
        DevLogger.shared.info("ScheduledRunMiniPanelWindowController deinit", context: "ScheduledRunMiniPanel")
        #endif
    }
}

extension ScheduledRunMiniPanelWindowController {
    /// Suppress unused-property warning during build until the
    /// resize-shrink path consumes ``collapsedHiddenContentSize``
    /// directly. Keeping the constant in the controller documents the
    /// intended floor for the panel even though the React side currently
    /// controls all height changes.
    fileprivate var _collapsedHiddenSizeKeepalive: NSSize { collapsedHiddenContentSize }
}
