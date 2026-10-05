import AppKit

extension AgentTaskResultWidgetController {
    func ensureProvisionalFailureObserver() {
        guard provisionalFailureObserver == nil else { return }
        provisionalFailureObserver = NotificationCenter.default.addObserver(
            forName: Notification.Name("AgentTaskProvisionalFailed"),
            object: nil,
            queue: .main
        ) { [weak self] note in
            // ``addObserver(forName:object:queue:using:)`` declares its
            // closure as ``@Sendable``. Even though we asked for ``.main``
            // delivery, Swift's strict-concurrency checker still treats
            // this body as a non-isolated context, so any synchronous
            // touch of our @MainActor state (``self.webView`` and the
            // main-actor-isolated ``sendProvisionalFailed`` method)
            // produces a Swift-6 warning. ``MainActor.assumeIsolated``
            // would be the zero-cost fix but it's macOS 14+; our package
            // deployment target is macOS 13, so we hop onto the main
            // actor with an unstructured Task instead. The cost is one
            // runloop tick, which is irrelevant for a notification that
            // fires at most once per failed audio capture.
            //
            // We extract the userInfo values BEFORE the actor hop so the
            // boundary is only ever crossed with Sendable value types
            // (Strings); this keeps us out of the Notification-not-
            // Sendable rabbit hole if strict concurrency is tightened
            // further later.
            guard let info = note.userInfo as? [String: Any] else { return }
            guard let agentTaskId = info["agentTaskId"] as? String, !agentTaskId.isEmpty else { return }
            let reason = (info["reason"] as? String) ?? "unknown"
            let message = (info["message"] as? String) ?? "Audio could not be processed."
            let rootTaskId = info["rootTaskId"] as? String
            let previousTaskId = info["previousTaskId"] as? String
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                #if DEBUG
                DevLogger.shared.info(
                    "[AgentTaskResult] Forwarding provisional failure for \(agentTaskId) (reason=\(reason)) to React",
                    context: "AgentTaskResult"
                )
                #endif
                self.webView?.sendProvisionalFailed(
                    agentTaskId: agentTaskId,
                    reason: reason,
                    message: message,
                    rootTaskId: rootTaskId,
                    previousTaskId: previousTaskId
                )
            }
        }
    }

    func show(
        placement: Placement,
        sidebarExpanded: Bool,
        initialAgentTaskId: String?,
        initiallyProcessing: Bool,
        initialAgentTask: String?,
        initialReferencePaths: [URL] = []
    ) {
        // Make sure we're listening for provisional-failure posts before any
        // capture VM can fire one. Idempotent (early-returns if already set).
        ensureProvisionalFailureObserver()

        if let panel = panel {
            // Already up; just bring it forward and dispatch any focus
            // request that came along with this call. Use
            // `makeKeyAndOrderFront` (not bare `orderFront`) so the panel
            // claims key-window status -- the main menu's Cmd+W key
            // equivalent (File > Close Window, action `performClose:`,
            // target nil) resolves through the KEY window's responder
            // chain, so without key status the menu item is disabled and
            // the keystroke drops silently.
            if panel.isMiniaturized { panel.deminiaturize(nil) }
            panel.makeKeyAndOrderFront(nil)
            if let cmdId = initialAgentTaskId {
                if initiallyProcessing {
                    dispatchOrQueueWebCommand(.register(agentTaskId: cmdId, referencePaths: initialReferencePaths))
                } else {
                    dispatchOrQueueWebCommand(.showExisting(agentTaskId: cmdId))
                }
            }
            return
        }

        let widgetSize = Self.standaloneInitialSize(sidebarExpanded: sidebarExpanded)

        let newPanel = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: widgetSize.width, height: widgetSize.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        newPanel.title = BasilTeamIdentity.agentTask.pairedName
        // ARC owns the panel via the strong `panel` property below; we
        // also nil that property in `dismiss()` to release. With AppKit's
        // default `isReleasedWhenClosed = true`, NSWindow's close cycle
        // would ALSO call `release` on the window, double-freeing it.
        // The X-button dismiss path avoided this by calling
        // `orderOut(nil)` + nil'ing `panel` without invoking `close()`,
        // but the new Cmd+W path goes through `WindowKeyboardShortcuts`
        // which calls `window.close()` directly -- that triggers the
        // full close cycle and crashes on the second release. Match
        // `ConversationWindowController`'s pattern and let ARC be the
        // sole owner.
        newPanel.isReleasedWhenClosed = false
        newPanel.level = .floating
        newPanel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]
        newPanel.hidesOnDeactivate = false
        newPanel.alphaValue = 1.0
        newPanel.isMovableByWindowBackground = true
        // `standaloneInitialSize` intentionally starts the history window at
        // the compact width even though the history sidebar is pre-expanded.
        // Do not immediately impose the expanded-sidebar minimum here:
        // AppKit applies it while constructing the window and turns that
        // deliberate compact initial frame into a wider, overlapping window
        // before WebKit has laid out its first view. The JS sizing bridge
        // updates the minimum to the actual rendered layout once that layout
        // exists.
        let initialMinimumSize = Self.standaloneMinimumSize(sidebarExpanded: false)
        newPanel.minSize = initialMinimumSize
        newPanel.contentMinSize = initialMinimumSize
        // Wire ourselves as the window delegate so the `windowWillClose:`
        // notification (fired by `WindowKeyboardShortcuts` below when it
        // calls `window.close()` on Cmd+W) lands on `dismiss()` and we
        // release the singleton self-retention. The `windowShouldClose:`
        // implementation further down is defensive only -- nothing in this
        // controller calls `performClose:`, and AppKit's main-menu Cmd+W
        // path can't reach it for borderless windows -- but it's left in
        // place so any future code path that goes through `performClose:`
        // also routes cleanly through `dismiss()`.
        newPanel.delegate = self

        // Translate Cmd+W into `newPanel.close()` while the panel is key.
        // See the `keyboardShortcuts` property doc for why this can't go
        // through the standard menu-equivalent dispatch.
        keyboardShortcuts = WindowKeyboardShortcuts(window: newPanel)
        collapseController = WindowCollapseController(
            window: newPanel,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: widgetSize
        )

        positionPanel(newPanel, size: widgetSize, placement: placement)
        // We deliberately call `makeKeyAndOrderFront` below (instead of
        // bare `orderFront`) so Cmd+W reaches us via the main menu's
        // key-equivalent dispatch -- see the matching comment on the
        // re-show branch above.

        let webView = AgentTaskResultWebView()
        isWebViewReady = false
        pendingWebCommands.removeAll()
        webView.initialSidebarExpanded = sidebarExpanded
        webView.initialAgentTaskId = initialAgentTaskId
        webView.initiallyProcessing = initiallyProcessing
        webView.initialAgentTask = initialAgentTask
        webView.initialReferencePaths = initialReferencePaths

        webView.onReady = { [weak self, weak webView] in
            guard let self = self, self.webView === webView else { return }
            self.handleWebViewReady()
        }

        // Self-dismiss on close. No transient parent: the widget owns
        // itself, so close cannot be silently no-op'd by a deallocated
        // owner the way it could when history hung off a capture
        // controller's lifetime.
        webView.onClose = { [weak self] in
            DispatchQueue.main.async { self?.dismiss() }
        }
        webView.onOpenDetachedAgentTask = { rootTaskId in
            DetachedAgentTaskWindowManager.shared.open(
                rootTaskId: rootTaskId,
                originatingWindow: newPanel
            )
        }
        webView.onOpenAgentTaskOrigin = { originType, originId in
            AgentTaskOriginNavigator.open(
                originType: originType,
                originId: originId,
                originatingWindow: newPanel
            )
        }
        webView.onAgentStatusChanged = { [weak self] agentTaskId, isProcessing, hasResult, _, supportsFollowUp in
            self?.updateFocusedRow(
                agentTaskId: agentTaskId,
                isProcessing: isProcessing,
                hasResult: hasResult,
                supportsFollowUp: supportsFollowUp
            )
            guard let self else { return }
            AgentTaskFollowUpFocusRegistry.shared.update(
                ownerID: self.followUpCaptureOwnerID,
                agentTaskId: agentTaskId,
                isProcessing: isProcessing,
                supportsFollowUp: supportsFollowUp
            )
        }
        webView.onFocusedAgentTaskCompleted = { [weak webView] in
            guard APIClient.shared.getCachedAgentTaskSettings().autoReopenOnCompletion else { return }
            webView?.sendExpandChromeForTaskCompletion()
        }

        webView.onMinimize = { [weak newPanel] in
            DispatchQueue.main.async { newPanel?.miniaturize(nil) }
        }

        webView.onResize = { [weak self, weak newPanel] request in
            guard let self, let panel = newPanel else { return }
            switch request.intent {
            case .collapsed:
                self.collapseController?.setCollapsed(true, preferredCompactSize: request.size)
            case .expanded:
                self.collapseController?.setCollapsed(false, fallbackExpandedSize: request.size)
            case .content:
                if let minimumWidth = request.minimumWidth {
                    let minimumSize = NSSize(width: minimumWidth, height: 300)
                    panel.minSize = minimumSize
                    panel.contentMinSize = minimumSize
                }
                WindowChromeCollapse.applyContentResize(
                    window: panel,
                    requestedSize: request.size
                )
            case .layout:
                if let minimumWidth = request.minimumWidth {
                    let minimumSize = NSSize(width: minimumWidth, height: 300)
                    panel.minSize = minimumSize
                    panel.contentMinSize = minimumSize
                }
                WindowChromeCollapse.applyLayoutResize(
                    window: panel,
                    requestedSize: request.size
                )
            }
        }

        // Follow-up captures stay inside this widget.
        webView.onStartFollowUpCapture = { [weak self] rootTaskId, previousTaskId in
            self?.handleFollowUpCaptureStart(
                rootTaskId: rootTaskId,
                previousTaskId: previousTaskId
            )
        }
        webView.onStopFollowUpCapture = { [weak self] in
            self?.handleFollowUpCaptureStop()
        }
        webView.onCancelFollowUpCapture = { [weak self] in
            self?.handleFollowUpCaptureCancel()
        }

        // New-AgentTask captures spawn a separate capture widget via the
        // externally-registered hook (StatusBarWindowCoordinator).
        webView.onStartNewAgentTaskCapture = { [weak self] preGeneratedId in
            if let externalHandler = self?.onStartNewAgentTaskCapture {
                externalHandler(preGeneratedId)
                return
            }

            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                appDelegate.statusBarManager?.windowCoordinator.showAgentTaskCaptureWidget(
                    preGeneratedAgentTaskId: preGeneratedId
                )
            }
        }
        webView.onStopNewAgentTaskCapture = { [weak self] in
            self?.onStopNewAgentTaskCapture?()
        }
        webView.onCancelNewAgentTaskCapture = { [weak self] in
            self?.onCancelNewAgentTaskCapture?()
        }

        // Refinement is a trivial state relay; handled internally.
        webView.onStartRefinementRecording = { [weak self] in
            self?.handleRefinementStart()
        }
        webView.onStopRefinementRecording = { [weak self] in
            self?.handleRefinementStop()
        }

        webView.onCancelRunningAgentTask = { agentTaskId in
            Task {
                DevLogger.shared.info(
                    "[AGENT_TASK] Dispatching REST cancellation for \(agentTaskId)",
                    context: "AgentTaskResult"
                )
                do {
                    try await performAgentTaskRESTCancellation(agentTaskId: agentTaskId)
                    DevLogger.shared.info(
                        "[AGENT_TASK] REST cancellation acknowledged for \(agentTaskId)",
                        context: "AgentTaskResult"
                    )
                } catch {
                    DevLogger.shared.error(
                        "[AGENT_TASK] REST cancellation failed for \(agentTaskId): \(error)",
                        context: "AgentTaskResult"
                    )
                }
            }
        }
        webView.onReportAgentTaskCancellationStage = { agentTaskId, stage in
            DevLogger.shared.info(
                "[AGENT_TASK] Cancellation stage=\(stage) task=\(agentTaskId)",
                context: "AgentTaskResult"
            )
        }

        webView.webView.alphaValue = 0
        newPanel.contentView = webView.webView
        WebKitWindowChromeAppearance.apply(to: newPanel)
        webView.installDragArea()
        webView.loadContent()

        self.panel = newPanel
        self.webView = webView
        AgentTaskResultPresentationCoordinator.shared.standaloneDidBecomeVisible()
        DetachedAgentTaskWindowManager.shared.addObserver(self)
        AgentTaskFollowUpFocusRegistry.shared.register(ownerID: followUpCaptureOwnerID) { [weak self] rootTaskId in
            self?.startFollowUpCapture(rootTaskId: rootTaskId)
        }
        AgentTaskFollowUpFocusRegistry.shared.setPrimary(ownerID: followUpCaptureOwnerID)

        newPanel.makeKeyAndOrderFront(nil)

        #if DEBUG
        DevLogger.shared.info(
            "📜 AgentTask result/history widget shown (self-owning singleton)",
            context: "AgentTaskResult"
        )
        #endif
    }
}
