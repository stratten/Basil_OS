import AppKit

/// Window controller for the Setup Assistant resume toast: a borderless,
/// non-activating `NSPanel` hosting a WKWebView-rendered React card, with
/// `WebKitWindowChromeAppearance` styling and `AppearanceRefreshCoordinator`
/// registration for live theme updates. The toast anchors near the menu-bar
/// icon for the duration of one launch decision, auto-dismissing after 20
/// seconds (treated as Remind me later -- the toast returns on next launch
/// unless the user explicitly picks Don't remind me again).
///
/// The panel stays hidden (`alphaValue == 0`, not ordered front) until the
/// web content reports its measured height via `requestResize`, so the user
/// never sees a wrong-sized placeholder card -- the same fix applied to the
/// Agent Desk interactive-overlay sizing issue.
@MainActor
final class SetupAssistantResumeToastWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    private var webViewHost: SetupAssistantResumeToastWebView?
    private var autoDismissTask: Task<Void, Never>?
    private var rendererReadyTimeoutTask: Task<Void, Never>?
    private let autoDismissAfter: TimeInterval = 20.0
    private static let toastWidth: CGFloat = 320

    func present(
        anchorFrame: NSRect?,
        onResume: @escaping () -> Void,
        onRemindLater: @escaping () -> Void,
        onDontRemind: @escaping () -> Void
    ) {
        guard panel == nil else {
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] present: ignored, a panel is already presented/pending")
            return
        }
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: starting, anchorFrame=\(anchorFrame.map(String.init(describing:)) ?? "nil")")

        let chromeInset = WebKitWindowChromeAppearance.frameInset
        // Generous placeholder height before the renderer reports its
        // measured height, so the card never wraps or clips while it is
        // still off-screen (alphaValue 0, not ordered front).
        let placeholderSize = NSSize(width: Self.toastWidth + chromeInset * 2, height: 260)

        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: placeholderSize),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        panel.title = "Resume Setup"
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.worksWhenModal = true
        panel.isReleasedWhenClosed = false
        panel.isMovableByWindowBackground = true
        panel.delegate = self
        panel.alphaValue = 0

        let webViewHost = SetupAssistantResumeToastWebView()
        self.webViewHost = webViewHost
        webViewHost.onRendererReady = { [weak self] in
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: rendererReady received, canceling timeout")
            self?.rendererReadyTimeoutTask?.cancel()
            self?.rendererReadyTimeoutTask = nil
        }
        webViewHost.onResizeRequested = { [weak self] size in
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: resize requested \(size)")
            self?.showAtMeasuredSize(size, anchorFrame: anchorFrame)
        }
        webViewHost.onResume = { [weak self] in
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: resume tapped")
            self?.dismiss()
            onResume()
        }
        webViewHost.onRemindLater = { [weak self] in
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: remindLater tapped")
            self?.dismiss()
            onRemindLater()
        }
        webViewHost.onDontRemind = { [weak self] in
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: dontRemind tapped")
            self?.dismiss()
            onDontRemind()
        }
        webViewHost.onNavigationFailed = {
            SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] present: SetupAssistantResumeToastWebView navigation failed to load")
        }
        panel.contentView = webViewHost.webView

        WebKitWindowChromeAppearance.apply(to: panel)
        panel.alphaValue = 0

        // Make the panel draggable. NSPanel.isMovableByWindowBackground is
        // set above but does nothing on its own here because the WKWebView
        // swallows mouse events; the drag area subview is what actually
        // promotes a click in the copy area into a window drag (mirrors
        // every other WKWebView-hosted panel).
        webViewHost.installDragArea()

        self.panel = panel
        webViewHost.loadContent()
        AppearanceRefreshCoordinator.shared.register(self)

        rendererReadyTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, let self, self.webViewHost != nil else { return }
            SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] present: renderer did not report ready within 3s timeout")
        }

        autoDismissTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(self?.autoDismissAfter ?? 20) * 1_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                guard let self, self.panel != nil else { return }
                SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] present: auto-dismiss timer fired after \(self.autoDismissAfter)s")
                self.dismiss()
                onRemindLater()
            }
        }
    }

    func dismiss() {
        autoDismissTask?.cancel()
        autoDismissTask = nil
        guard let panel else {
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] dismiss: no-op, nothing presented")
            return
        }
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] dismiss: hiding and tearing down")
        self.panel = nil
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.18
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            Task { @MainActor in
                panel.orderOut(nil)
                self?.cleanup()
            }
        })
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    // MARK: - Private

    private func cleanup() {
        rendererReadyTimeoutTask?.cancel()
        rendererReadyTimeoutTask = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        webViewHost?.tearDown()
        webViewHost = nil
        panel?.delegate = nil
    }

    private func showAtMeasuredSize(_ contentSize: CGSize, anchorFrame: NSRect?) {
        guard let panel else {
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] showAtMeasuredSize: ignored, no panel (already dismissed?)")
            return
        }
        guard panel.alphaValue == 0 else {
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] showAtMeasuredSize: ignored, panel already visible (alphaValue=\(panel.alphaValue))")
            return
        }
        let chromeInset = WebKitWindowChromeAppearance.frameInset
        let panelSize = NSSize(
            width: Self.toastWidth + chromeInset * 2,
            height: contentSize.height + chromeInset * 2
        )
        panel.setContentSize(panelSize)
        positionPanel(panel, near: anchorFrame, panelSize: panelSize)
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] showAtMeasuredSize: ordering front at frame=\(panel.frame)")
        panel.orderFront(nil)
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.2
            panel.animator().alphaValue = 1
        }
    }

    private func positionPanel(_ panel: NSPanel, near anchorFrame: NSRect?, panelSize: NSSize) {
        let screen = NSScreen.main ?? NSScreen.screens.first
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let margin: CGFloat = 16

        if let anchor = anchorFrame {
            let originX = min(
                max(anchor.midX - panelSize.width / 2, visible.minX + margin),
                visible.maxX - panelSize.width - margin
            )
            let originY = anchor.minY - panelSize.height - 8
            panel.setFrameOrigin(NSPoint(x: originX, y: originY))
        } else {
            let originX = visible.maxX - panelSize.width - margin
            let originY = visible.maxY - panelSize.height - margin
            panel.setFrameOrigin(NSPoint(x: originX, y: originY))
        }
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
    }
}
