import AppKit
import SwiftUI

// MARK: - Setup Assistant Window

extension AppDelegate {
    @MainActor
    private var setupWindowHorizontalChrome: CGFloat {
        WebKitWindowChromeAppearance.frameInset * 2
    }

    @MainActor
    private var setupWindowVerticalChrome: CGFloat {
        WebKitWindowChromeAppearance.frameInset * 2
            + SetupWindowDragAreaInstaller.headerHeight
    }

    func presentPrimarySetupAssistantFlowFromDelegate() {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.presentSetupAssistantWindowFromDelegate()
        }
    }

    @MainActor
    func presentSetupAssistantWindowFromDelegate() {
        guard setupAssistantWindow == nil else {
            setupAssistantWindow?.makeKeyAndOrderFront(nil)
            return
        }

        let setupAssistantView = SetupAssistantWebView(
            onRestartRequested: { [weak self] in
                self?.restartApplicationFromSetupAssistant()
            },
            onCloseRequested: { [weak self] in
                self?.setupAssistantWindow?.close()
            },
            onMinimizeRequested: { [weak self] in
                self?.setupAssistantWindow?.miniaturize(nil)
            },
            onResizeRequested: { [weak self] height in
                guard let self, let window = self.setupAssistantWindow else { return }
                let constrainedHeight = min(
                    max(height, 620 + self.setupWindowVerticalChrome),
                    1200 + self.setupWindowVerticalChrome
                )
                WindowChromeCollapse.applyLayoutResize(
                    window: window,
                    requestedSize: NSSize(
                        width: window.frame.width,
                        height: constrainedHeight
                    )
                )
            },
            onCollapseRequested: { [weak self] in
                self?.setupAssistantCollapseController?.setCollapsed(true)
            },
            onExpandRequested: { [weak self] in
                self?.setupAssistantCollapseController?.setCollapsed(false)
            },
            onCoordinatorReady: { [weak self] coordinator in
                self?.setupAssistantThemeCoordinator = coordinator
                AppearanceRefreshCoordinator.shared.register(coordinator)
            }
        )

        let window = CustomBorderlessWindow(
            contentRect: NSRect(
                x: 0,
                y: 0,
                width: 1180 + setupWindowHorizontalChrome,
                height: 760 + setupWindowVerticalChrome
            ),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Basil Setup Assistant"
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true
        window.contentView = NSHostingView(
            rootView: setupAssistantView
                .preferredColorScheme(.light)
        )
        WebKitWindowChromeAppearance.apply(to: window)
        window.contentMinSize = NSSize(
            width: 980 + setupWindowHorizontalChrome,
            height: 620 + setupWindowVerticalChrome
        )
        window.contentMaxSize = NSSize(
            width: 3000 + setupWindowHorizontalChrome,
            height: 3000 + setupWindowVerticalChrome
        )

        let targetScreen = NSApp.keyWindow?.screen ?? NSScreen.main
        if let screen = targetScreen {
            window.setFrame(
                WindowChromeCollapse.centeredFrame(
                    requestedSize: window.frame.size,
                    minSize: window.minSize,
                    visibleFrame: screen.visibleFrame
                ),
                display: false,
                animate: false
            )
        } else {
            window.center()
        }

        NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification,
            object: window,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                guard let appDelegate = NSApp.delegate as? AppDelegate else { return }
                if let coordinator = appDelegate.setupAssistantThemeCoordinator {
                    AppearanceRefreshCoordinator.shared.unregister(coordinator)
                }
                appDelegate.setupAssistantThemeCoordinator = nil
                appDelegate.setupAssistantKeyboardShortcuts = nil
                appDelegate.setupAssistantCollapseController = nil
                appDelegate.setupAssistantWindow = nil
            }
        }

        setupAssistantWindow = window
        setupAssistantKeyboardShortcuts = WindowKeyboardShortcuts(window: window)
        setupAssistantCollapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(
                width: 1180 + setupWindowHorizontalChrome,
                height: 760 + setupWindowVerticalChrome
            )
        )
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @MainActor
    func presentSetupPermissionsWindowFromDelegate(
        autoPresented: Bool = false,
        continueToSetupAssistant: Bool = false,
        isReturningUserCheck: Bool = false
    ) {
        guard setupPermissionsWindow == nil else {
            setupPermissionsWindow?.makeKeyAndOrderFront(nil)
            return
        }

        let permissionsView = SetupPermissionsWebView(
            isReturningUserCheck: isReturningUserCheck,
            onRestartRequested: { [weak self] in
                self?.restartApplicationFromSetupAssistant()
            },
            onContinueRequested: { [weak self] in
                Task { @MainActor in
                    guard let self else { return }
                    let status = await SetupPermissionsStatusEvaluator.currentStatus()
                    guard status.allRequiredPermissionsGranted else {
                        self.presentSetupPermissionsWindowFromDelegate(autoPresented: autoPresented)
                        return
                    }
                    self.setupPermissionsWindow?.close()
                    if continueToSetupAssistant {
                        self.presentSetupAssistantWindowFromDelegate()
                    }
                }
            },
            onCloseRequested: { [weak self] in
                self?.setupPermissionsWindow?.close()
            },
            onMinimizeRequested: { [weak self] in
                self?.setupPermissionsWindow?.miniaturize(nil)
            },
            onCollapseRequested: { [weak self] in
                self?.setupPermissionsCollapseController?.setCollapsed(true)
            },
            onExpandRequested: { [weak self] in
                self?.setupPermissionsCollapseController?.setCollapsed(false)
            },
            onCoordinatorReady: { [weak self] coordinator in
                self?.setupPermissionsThemeCoordinator = coordinator
                AppearanceRefreshCoordinator.shared.register(coordinator)
            },
            onLoadFailed: { [weak self] in
                self?.showSetupPermissionsLoadFailureAlert()
            }
        )

        let window = CustomBorderlessWindow(
            contentRect: NSRect(
                x: 0,
                y: 0,
                width: 940 + setupWindowHorizontalChrome,
                height: 660 + setupWindowVerticalChrome
            ),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = isReturningUserCheck
            ? "Welcome Back"
            : (autoPresented ? "Basil Permissions Required" : "Basil Permissions Setup")
        window.isReleasedWhenClosed = false
        window.isMovableByWindowBackground = true
        window.contentView = NSHostingView(
            rootView: permissionsView
                .preferredColorScheme(.light)
        )
        WebKitWindowChromeAppearance.apply(to: window)
        window.contentMinSize = NSSize(
            width: 760 + setupWindowHorizontalChrome,
            height: 540 + setupWindowVerticalChrome
        )
        window.contentMaxSize = NSSize(
            width: 1400 + setupWindowHorizontalChrome,
            height: 1200 + setupWindowVerticalChrome
        )

        let targetScreen = NSApp.keyWindow?.screen ?? NSScreen.main
        if let screen = targetScreen {
            let screenFrame = screen.visibleFrame
            let windowSize = window.frame.size
            let newOriginX = screenFrame.midX - windowSize.width / 2
            let newOriginY = screenFrame.midY - windowSize.height / 2
            window.setFrameOrigin(NSPoint(x: newOriginX, y: newOriginY))
        } else {
            window.center()
        }

        NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification,
            object: window,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                guard let appDelegate = NSApp.delegate as? AppDelegate else { return }
                if let coordinator = appDelegate.setupPermissionsThemeCoordinator {
                    AppearanceRefreshCoordinator.shared.unregister(coordinator)
                }
                appDelegate.setupPermissionsThemeCoordinator = nil
                appDelegate.setupPermissionsKeyboardShortcuts = nil
                appDelegate.setupPermissionsCollapseController = nil
                appDelegate.setupPermissionsWindow = nil
            }
        }

        setupPermissionsWindow = window
        setupPermissionsKeyboardShortcuts = WindowKeyboardShortcuts(window: window)
        setupPermissionsCollapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(
                width: 940 + setupWindowHorizontalChrome,
                height: 660 + setupWindowVerticalChrome
            )
        )
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func presentSetupPermissionsWindowIfRequiredFromDelegate() {
        Task { @MainActor [weak self] in
            let status = await SetupPermissionsStatusEvaluator.currentStatus()
            guard !status.allRequiredPermissionsGranted else { return }
            self?.presentSetupPermissionsWindowFromDelegate(autoPresented: true, isReturningUserCheck: true)
        }
    }

    /// Minimal native failure surface for the guardrail that the setup
    /// permissions bundle must not fail silently into a blank window. Shown
    /// only when the packaged web assets themselves cannot be found/loaded.
    @MainActor
    private func showSetupPermissionsLoadFailureAlert() {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Basil couldn't load its setup screen."
        alert.informativeText = "Try restarting the app. If this keeps happening, reinstalling Basil may help."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    /// Show the resume toast at most once per launch, only when the user
    /// previously hit "Skip setup for now" and has not asked us to stop
    /// reminding them. Safe to call from ``applicationDidFinishLaunching``
    /// after the backend task has started — the loader has its own 4s
    /// timeout and silently no-ops if the backend has not finished booting.
    @MainActor
    func presentSetupAssistantResumeToastIfPendingFromDelegate() {
        guard !hasShownSetupAssistantResumeToastThisLaunch else { return }
        hasShownSetupAssistantResumeToastThisLaunch = true

        Task { @MainActor in
            let pendingState = SetupAssistantPendingStateModel()
            await pendingState.loadFromBackend()
            guard pendingState.shouldShowLaunchResumeToast else {
                #if DEBUG
                DevLogger.shared.info(
                    "[SetupAssistant] Resume toast skipped (pending=\(pendingState.pendingSetupAssistant), dismissed=\(pendingState.reminderDismissed))",
                    context: "SetupAssistant"
                )
                #endif
                return
            }

            let controller = setupAssistantResumeToastController ?? SetupAssistantResumeToastWindowController()
            setupAssistantResumeToastController = controller

            // Anchor below the menu-bar icon when we can — otherwise the
            // controller falls back to the top-right of the visible screen.
            let anchorFrame = statusBarManager?.statusBarItem.statusItem?.button?.window?.frame

            controller.present(
                anchorFrame: anchorFrame,
                onResume: { [weak self] in
                    self?.presentSetupAssistantWindowFromDelegate()
                },
                onRemindLater: {
                    // No backend write: the pending flag is still true, so the
                    // toast will surface again on the next launch.
                },
                onDontRemind: {
                    Task { @MainActor in
                        await pendingState.dismissReminder()
                    }
                }
            )
        }
    }

    /// Developer-menu-only entry point for visually testing the resume
    /// toast on demand. Reuses the exact same
    /// `SetupAssistantResumeToastWindowController.present(...)` call as the
    /// real launch-time path above, just without the "already shown this
    /// launch"/backend-pending-state gating, so it can be re-triggered
    /// repeatedly without restarting the app or mutating setup-assistant
    /// state.
    #if DEBUG
    @MainActor
    func triggerSetupAssistantResumeToastForDebugFromDelegate() {
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistant] Debug menu: Trigger Setup Assistant Resume Toast selected")
        let controller = setupAssistantResumeToastController ?? SetupAssistantResumeToastWindowController()
        setupAssistantResumeToastController = controller

        let anchorFrame = statusBarManager?.statusBarItem.statusItem?.button?.window?.frame
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistant] Debug menu: resolved anchorFrame=\(anchorFrame.map(String.init(describing:)) ?? "nil")")

        controller.present(
            anchorFrame: anchorFrame,
            onResume: { [weak self] in
                self?.presentSetupAssistantWindowFromDelegate()
            },
            onRemindLater: {
                SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistant] Debug toast: Remind me later tapped")
            },
            onDontRemind: {
                SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistant] Debug toast: Don't remind me again tapped")
            }
        )
    }
    #endif

    private func restartApplicationFromSetupAssistant() {
        guard let bundleURL = Bundle.main.bundleURL as URL? else {
            NSApplication.shared.terminate(nil)
            return
        }

        let configuration = NSWorkspace.OpenConfiguration()
        configuration.createsNewApplicationInstance = true

        NSWorkspace.shared.openApplication(
            at: bundleURL,
            configuration: configuration
        ) { _, error in
            #if DEBUG
            if let error = error {
                DevLogger.shared.error("Failed to relaunch Basil from setup assistant: \(error)", context: "SetupAssistant")
            }
            #endif
            NSApplication.shared.terminate(nil)
        }
    }
}
