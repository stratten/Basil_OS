import AppKit

/// Window controller for the trial-exhaustion alert. Mirrors
/// `ModelDownloadWindowController`'s shape: a borderless `NSPanel` hosting a
/// WKWebView-rendered React panel, with `WebKitWindowChromeAppearance`
/// styling and `AppearanceRefreshCoordinator` registration for live theme
/// updates.
@MainActor
final class TrialExhaustionWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    static let shared = TrialExhaustionWindowController()

    private var panel: NSPanel?
    private var webViewHost: TrialExhaustionPanelWebView?
    private var rendererReadyTimeoutTask: Task<Void, Never>?

    private static let panelWidth: CGFloat = 480
    /// Generous placeholder height before the renderer reports its measured
    /// height, so the card never wraps or clips while it is still hidden
    /// (`alphaValue == 0`, ordered front but invisible).
    private static let placeholderHeight: CGFloat = 500

    var isVisible: Bool { panel != nil && (panel?.isVisible ?? false) }

    // MARK: - Public API

    func show() {
        guard panel == nil else {
            panel?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.panelWidth, height: Self.placeholderHeight),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        panel.title = "Continue with Basil Cloud"
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
        panel.isMovableByWindowBackground = true
        panel.isReleasedWhenClosed = false
        panel.delegate = self
        panel.center()
        panel.alphaValue = 0

        let webViewHost = TrialExhaustionPanelWebView()
        self.webViewHost = webViewHost
        webViewHost.onRendererReady = { [weak self] in
            self?.rendererReadyTimeoutTask?.cancel()
            self?.rendererReadyTimeoutTask = nil
        }
        webViewHost.onResizeRequested = { [weak self] size in
            self?.showAtMeasuredSize(size)
        }
        webViewHost.onDismiss = { [weak self] in
            self?.dismiss()
        }
        webViewHost.onSignUp = {
            Self.handleSignUp()
        }
        webViewHost.onAddOwnKeys = {
            Self.handleAddOwnKeys()
        }
        webViewHost.onUseLocalModels = { [weak self] requestId in
            self?.handleUseLocalModels(requestId: requestId)
        }
        webViewHost.onNavigationFailed = {
            #if DEBUG
            DevLogger.shared.error("TrialExhaustionPanel navigation failed to load", context: "TrialExhaustion")
            #endif
        }
        panel.contentView = webViewHost.webView

        WebKitWindowChromeAppearance.apply(to: panel)

        // Make the panel draggable. NSPanel.isMovableByWindowBackground is
        // set above but does nothing on its own here because the WKWebView
        // swallows mouse events; the drag area subview is what actually
        // promotes a click in the header strip into a window drag (mirrors
        // every other WKWebView-hosted panel).
        webViewHost.installDragArea()

        self.panel = panel
        webViewHost.loadContent(payload: Self.currentPayload())
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        AppearanceRefreshCoordinator.shared.register(self)

        rendererReadyTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, let self, self.webViewHost != nil else { return }
            #if DEBUG
            DevLogger.shared.error("TrialExhaustionPanel renderer did not report ready within timeout", context: "TrialExhaustion")
            #endif
        }

        #if DEBUG
        DevLogger.shared.info("TrialExhaustionWindowController shown", context: "TrialExhaustion")
        #endif
    }

    func dismiss() {
        guard let panel else { return }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.2
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            Task { @MainActor in
                panel.orderOut(nil)
                self?.cleanup()
            }
        })

        #if DEBUG
        DevLogger.shared.info("TrialExhaustionWindowController dismissed", context: "TrialExhaustion")
        #endif
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    // MARK: - Private

    private func showAtMeasuredSize(_ contentSize: CGSize) {
        guard let panel else { return }
        guard panel.alphaValue == 0 else { return }
        panel.setContentSize(NSSize(width: Self.panelWidth, height: contentSize.height))
        panel.center()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            panel.animator().alphaValue = 1
        }
    }

    private static func currentPayload() -> TrialExhaustionPanelWebView.InitPayload {
        let manager = TrialExhaustionManager.shared
        return TrialExhaustionPanelWebView.InitPayload(
            remainingBalanceFormatted: manager.remainingBalanceFormatted,
            limitFormatted: manager.limitFormatted,
            isAuthenticated: AuthService.shared.isAuthenticated,
            userEmail: AuthService.shared.currentUser?.email
        )
    }

    private func cleanup() {
        rendererReadyTimeoutTask?.cancel()
        rendererReadyTimeoutTask = nil
        webViewHost?.tearDown()
        webViewHost = nil
        panel?.delegate = nil
        panel = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
    }

    private static func handleSignUp() {
        TrialExhaustionWindowController.shared.dismiss()
        TrialExhaustionManager.shared.clearTrialState()
        NotificationCenter.default.post(
            name: Notification.Name("navigateToSettings"),
            object: nil,
            userInfo: ["section": "account", "action": AuthService.shared.isAuthenticated ? "billing" : "signin"]
        )
    }

    private static func handleAddOwnKeys() {
        TrialExhaustionWindowController.shared.dismiss()
        TrialExhaustionManager.shared.clearTrialState()
        NotificationCenter.default.post(
            name: Notification.Name("navigateToSettings"),
            object: nil,
            userInfo: ["section": "api_keys", "action": "add"]
        )
    }

    private func handleUseLocalModels(requestId: String) {
        Task {
            do {
                let settings = AuthSettingsUpdate(
                    apiKeyPreference: "local",
                    isAuthenticated: AuthService.shared.isAuthenticated,
                    userEmail: AuthService.shared.currentUser?.email
                )
                try await APIClient.shared.updateAuthSettings(settings)
                await MainActor.run {
                    TrialExhaustionManager.shared.clearTrialState()
                    self.webViewHost?.sendUseLocalModelsResult(requestId: requestId, status: "success")
                }
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to update to local models: \(error.localizedDescription)", context: "TrialExhaustion")
                #endif
                await MainActor.run {
                    self.webViewHost?.sendUseLocalModelsResult(requestId: requestId, status: "failure", message: error.localizedDescription)
                }
            }
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
        #if DEBUG
        DevLogger.shared.info("TrialExhaustionWindowController deinit", context: "TrialExhaustion")
        #endif
    }
}
