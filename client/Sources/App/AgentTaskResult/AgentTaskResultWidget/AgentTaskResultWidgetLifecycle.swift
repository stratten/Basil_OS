import AppKit

extension AgentTaskResultWidgetController {
    /// Show the widget standalone with the history sidebar pre-expanded.
    /// Called from the capture widget's "show history" button and from
    /// anywhere else that just wants to surface history.
    @discardableResult
    static func showStandaloneHistory(anchorFrame: NSRect? = nil) -> AgentTaskResultWidgetController {
        let instance = ensureShared()
        let placement: Placement = anchorFrame.map { .anchoredLeftOfFrame($0) } ?? .topRightLeavingCaptureSpace
        instance.show(
            placement: placement,
            sidebarExpanded: true,
            initialAgentTaskId: nil,
            initiallyProcessing: false,
            initialAgentTask: nil
        )
        return instance
    }

    /// Fold a new agent into the widget. Called by the capture controller
    /// once processing starts. If the widget isn't yet on screen, it is
    /// created with the new AgentTask pre-focused; if it is, the new
    /// AgentTask is registered and selected via the JS bridge.
    @discardableResult
    static func installNewAgent(
        agentTaskId: String,
        initialAgentTask: String?,
        anchorFrame: NSRect? = nil,
        placement: Placement? = nil,
        initialReferencePaths: [URL] = []
    ) -> AgentTaskResultWidgetController {
        let instance = ensureShared()
        let resolvedPlacement = placement
            ?? anchorFrame.map { .anchoredLeftOfFrame($0) }
            ?? .topRightLeavingCaptureSpace
        if instance.panel == nil {
            instance.show(
                placement: resolvedPlacement,
                sidebarExpanded: false,
                initialAgentTaskId: agentTaskId,
                initiallyProcessing: true,
                initialAgentTask: initialAgentTask,
                initialReferencePaths: initialReferencePaths
            )
        } else {
            instance.dispatchOrQueueWebCommand(.register(agentTaskId: agentTaskId, referencePaths: initialReferencePaths))
            instance.bringToFront()
        }
        return instance
    }

    /// Show the widget focused on an already-running or completed
    /// AgentTask (e.g., from the scheduled-run mini panel's row click).
    /// Reuses the live widget if present.
    @discardableResult
    static func showExistingAgentTask(
        agentTaskId: String,
        anchorFrame: NSRect? = nil
    ) -> AgentTaskResultWidgetController {
        let instance = ensureShared()
        let placement: Placement = anchorFrame.map { .anchoredLeftOfFrame($0) } ?? .topRightLeavingCaptureSpace
        if instance.panel == nil {
            instance.show(
                placement: placement,
                sidebarExpanded: false,
                initialAgentTaskId: agentTaskId,
                initiallyProcessing: false,
                initialAgentTask: nil
            )
        } else {
            instance.dispatchOrQueueWebCommand(.showExisting(agentTaskId: agentTaskId))
            instance.bringToFront()
        }
        return instance
    }

    static func ensureShared() -> AgentTaskResultWidgetController {
        if let existing = shared { return existing }
        let instance = AgentTaskResultWidgetController()
        shared = instance
        return instance
    }

    static func dismissShared() {
        shared?.dismiss()
    }

    static func requestValidationManagedHistoryRestore(requestId: String) {
        shared?.dispatchOrQueueWebCommand(.restoreValidationManagedHistory(requestId: requestId))
    }

    /// Tear down the panel and webview and release self-retention so the
    /// controller deallocates. Idempotent — safe to call when nothing is
    /// open.
    func dismiss() {
        AgentTaskResultPresentationCoordinator.shared.standaloneDidDismiss()
        DetachedAgentTaskWindowManager.shared.removeObserver(self)

        // Cancel any in-flight follow-up capture first so the audio
        // pipeline shuts down cleanly before we drop our last reference.
        if followUpCaptureVM != nil {
            handleFollowUpCaptureCancel()
        }

        guard panel != nil else {
            // Still clear shared in case a stray reference is being held.
            Self.shared = nil
            return
        }

        #if DEBUG
        DevLogger.shared.info(
            "📜 Dismissing agentTask result/history widget",
            context: "AgentTaskResult"
        )
        #endif

        // Detach the delegate before dropping our reference so AppKit can't
        // call back into a deallocated controller (we self-retain via
        // `Self.shared`, which is cleared at the bottom of this method).
        panel?.delegate = nil

        // Remove the per-window key monitor BEFORE we drop the panel
        // reference. `WindowKeyboardShortcuts` holds the panel weakly so
        // it'd nil out on its own eventually, but its event closure also
        // captures `self` (the helper) and runs on every keystroke until
        // explicit `cleanup()`. Releasing it here keeps the global event
        // tap roster tidy and avoids a benign-but-wasteful no-op handler
        // firing for every keypress in the app between dismiss and the
        // next time the widget is shown.
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        AgentTaskFollowUpFocusRegistry.shared.unregister(ownerID: followUpCaptureOwnerID)

        panel?.orderOut(nil)
        panel = nil
        webView?.tearDown()
        webView = nil
        isWebViewReady = false
        pendingWebCommands.removeAll()
        focusedRowState = nil

        if let observer = provisionalFailureObserver {
            NotificationCenter.default.removeObserver(observer)
            provisionalFailureObserver = nil
        }

        Self.shared = nil
    }

    /// Routes the standard Cmd+W menu equivalent (and any other AppKit-
    /// initiated close request, e.g. Window > Close) through our own
    /// teardown path. Returning `false` is intentional: ``dismiss()``
    /// already orders the panel out and drops every Swift-side
    /// reference, so letting AppKit also run its own `close()` cycle
    /// would be redundant and could fire delegate callbacks against a
    /// half-torn-down controller. Mirrors the pattern used by
    /// ``ConversationWindowController``.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        dismiss()
        return false
    }

    /// Fired by AppKit when the underlying NSWindow actually closes.
    /// In practice the trigger is `WindowKeyboardShortcuts` calling
    /// `newPanel.close()` on Cmd+W -- `close()` (unlike `performClose:`)
    /// goes straight through and does NOT consult `windowShouldClose:`,
    /// so without this hook the singleton would leak: the window would
    /// disappear from screen but `Self.shared`, `panel`, `webView`, and
    /// the keyboard-shortcuts monitor would all stay alive.
    /// `dismiss()` is idempotent, so it's safe even if other paths
    /// (X button, programmatic dismissal) have already torn down.
    func windowWillClose(_ notification: Notification) {
        guard let closingWindow = notification.object as? NSWindow,
              closingWindow === panel else { return }
        dismiss()
    }

    func windowDidBecomeKey(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.focus(ownerID: followUpCaptureOwnerID)
    }

    func windowDidResignKey(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.resignFocus(ownerID: followUpCaptureOwnerID)
    }

    func windowDidMiniaturize(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.resignFocus(ownerID: followUpCaptureOwnerID)
        AgentTaskFollowUpFocusRegistry.shared.clearPrimary(ownerID: followUpCaptureOwnerID)
    }

    func windowDidDeminiaturize(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.setPrimary(ownerID: followUpCaptureOwnerID)
    }

    func bringToFront() {
        guard let panel = panel else { return }
        if panel.isMiniaturized { panel.deminiaturize(nil) }
        // `makeKeyAndOrderFront` (not `orderFront`) so Cmd+W's
        // main-menu key-equivalent dispatch finds us via the key
        // window's responder chain. See `show()` for the full
        // rationale.
        panel.makeKeyAndOrderFront(nil)
    }
}
