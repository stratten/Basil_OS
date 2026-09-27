import AppKit
import Foundation
@MainActor
extension AppDelegate {
    func configureValidationLaunch() {
        NSApplication.shared.setActivationPolicy(.regular)
        Task {
            await APIClient.shared.updatePortAndCheckStatus()
            publishValidationProbe(backendAvailable: APIClient.shared.isBackendAvailable)
        }
    }

    func validationMenuItem() -> NSMenuItem {
        let menuItem = NSMenuItem(title: "Validation", action: nil, keyEquivalent: "")
        let menu = NSMenu(title: "Validation")

        let settingsItem = menu.addItem(
            withTitle: "Open Settings",
            action: #selector(openValidationSettings(_:)),
            keyEquivalent: ""
        )
        settingsItem.target = self
        menu.addItem(NSMenuItem.separator())

        let workspaceItem = menu.addItem(
            withTitle: "Open Fixture Workspace",
            action: #selector(openValidationFixtureWorkspace(_:)),
            keyEquivalent: ""
        )
        workspaceItem.target = self

        let agentTasksItem = menu.addItem(
            withTitle: "Open Agent-Task Fixtures",
            action: #selector(openValidationAgentTaskFixtures(_:)),
            keyEquivalent: ""
        )
        agentTasksItem.target = self

        let runHistoryItem = menu.addItem(
            withTitle: "Open Multi-Run Agent-Task Fixture",
            action: #selector(openValidationRunHistoryFixture(_:)),
            keyEquivalent: ""
        )
        runHistoryItem.target = self

        let closeRunHistoryItem = menu.addItem(
            withTitle: "Close Multi-Run Agent-Task Fixture",
            action: #selector(closeValidationRunHistoryFixture(_:)),
            keyEquivalent: ""
        )
        closeRunHistoryItem.target = self

        let assertRunHistoryItem = menu.addItem(
            withTitle: "Assert Multi-Run Initial Focus",
            action: #selector(assertValidationRunHistoryInitialFocus(_:)),
            keyEquivalent: ""
        )
        assertRunHistoryItem.target = self

        let focusRunHistoryRootItem = menu.addItem(
            withTitle: "Focus Multi-Run Root",
            action: #selector(focusValidationRunHistoryRoot(_:)),
            keyEquivalent: ""
        )
        focusRunHistoryRootItem.target = self

        let focusRunHistoryMiddleItem = menu.addItem(
            withTitle: "Focus Multi-Run Middle",
            action: #selector(focusValidationRunHistoryMiddle(_:)),
            keyEquivalent: ""
        )
        focusRunHistoryMiddleItem.target = self

        let focusRunHistoryNewestItem = menu.addItem(
            withTitle: "Focus Multi-Run Newest",
            action: #selector(focusValidationRunHistoryNewest(_:)),
            keyEquivalent: ""
        )
        focusRunHistoryNewestItem.target = self

        let htmlPreviewItem = menu.addItem(
            withTitle: "Open HTML Preview Fixture",
            action: #selector(openValidationHTMLPreviewFixture(_:)),
            keyEquivalent: ""
        )
        htmlPreviewItem.target = self

        let htmlFeedbackItem = menu.addItem(
            withTitle: "Submit HTML Preview Feedback Fixture",
            action: #selector(submitValidationHTMLPreviewFeedback(_:)),
            keyEquivalent: ""
        )
        htmlFeedbackItem.target = self

        let localServerPreviewItem = menu.addItem(
            withTitle: "Open Local Server Preview Fixture",
            action: #selector(openValidationLocalServerPreviewFixture(_:)),
            keyEquivalent: ""
        )
        localServerPreviewItem.target = self

        let openLocalServerPreviewTaskItem = menu.addItem(
            withTitle: "Open Local Server Preview Task Fixture",
            action: #selector(openValidationLocalServerPreviewTaskFixture(_:)),
            keyEquivalent: ""
        )
        openLocalServerPreviewTaskItem.target = self

        let localServerPreviewFeedbackItem = menu.addItem(
            withTitle: "Submit Local Server Preview Feedback Fixture",
            action: #selector(submitValidationLocalServerPreviewFeedback(_:)),
            keyEquivalent: ""
        )
        localServerPreviewFeedbackItem.target = self

        let closePreviewWindowItem = menu.addItem(
            withTitle: "Close Local Preview Window",
            action: #selector(closeValidationPreviewWindow(_:)),
            keyEquivalent: ""
        )
        closePreviewWindowItem.target = self

        let managedHistoryItem = menu.addItem(
            withTitle: "Open Managed History Fixture",
            action: #selector(openValidationManagedHistoryFixture(_:)),
            keyEquivalent: ""
        )
        managedHistoryItem.target = self

        let closeManagedHistoryItem = menu.addItem(
            withTitle: "Close Managed History Fixture",
            action: #selector(closeValidationManagedHistoryFixture(_:)),
            keyEquivalent: ""
        )
        closeManagedHistoryItem.target = self

        let restoreManagedHistoryItem = menu.addItem(
            withTitle: "Restore Managed History Fixture",
            action: #selector(restoreValidationManagedHistoryFixture(_:)),
            keyEquivalent: ""
        )
        restoreManagedHistoryItem.target = self

        menu.addItem(NSMenuItem.separator())
        let revealSessionItem = menu.addItem(
            withTitle: "Reveal Validation Session Folder",
            action: #selector(revealValidationSessionFolder(_:)),
            keyEquivalent: ""
        )
        revealSessionItem.target = self
        menuItem.submenu = menu
        return menuItem
    }

    @objc private func openValidationSettings(_ sender: Any?) {
        SettingsShellWindowController.shared.show()
    }

    @objc private func openValidationFixtureWorkspace(_ sender: Any?) {
        showBasilBoard()
    }

    @objc private func openValidationAgentTaskFixtures(_ sender: Any?) {
        AgentTaskResultWidgetController.showStandaloneHistory()
    }

    @objc private func openValidationRunHistoryFixture(_ sender: Any?) {
        // Package 5B's multi-run history tray and newest-run default only
        // hydrate through the detached-window chain path (`hydrateDetachedChain`,
        // driven by `detachedRootTaskId`). `showExistingAgentTask` routes to the
        // shared standalone widget's single-task hydration (`hydrateAgentFromBackend`),
        // which never populates `agentTaskHistory`, so it can never show this
        // fixture's chain. Open the actual detached window so the fixture
        // exercises the real feature it is meant to validate.
        DetachedAgentTaskWindowManager.shared.open(
            rootTaskId: "validation-run-history-root"
        )
    }

    @objc private func closeValidationRunHistoryFixture(_ sender: Any?) {
        DetachedAgentTaskWindowManager.shared.close(rootTaskId: "validation-run-history-root")
    }

    @objc private func assertValidationRunHistoryInitialFocus(_ sender: Any?) {
        DetachedAgentTaskWindowManager.shared.requestValidationRunState(
            rootTaskId: "validation-run-history-root",
            requestId: UUID().uuidString
        )
    }

    @objc private func focusValidationRunHistoryRoot(_ sender: Any?) {
        focusValidationRunHistory(runId: "validation-run-history-root")
    }

    @objc private func focusValidationRunHistoryMiddle(_ sender: Any?) {
        focusValidationRunHistory(runId: "validation-run-history-follow-up-1")
    }

    @objc private func focusValidationRunHistoryNewest(_ sender: Any?) {
        focusValidationRunHistory(runId: "validation-run-history-follow-up-2")
    }

    private func focusValidationRunHistory(runId: String) {
        DetachedAgentTaskWindowManager.shared.focusValidationRun(
            rootTaskId: "validation-run-history-root",
            requestId: UUID().uuidString,
            runId: runId
        )
    }

    @objc private func openValidationHTMLPreviewFixture(_ sender: Any?) {
        guard let sessionRootURL = BasilRuntimeProfile.sessionRootURL else {
            return
        }
        let htmlURL = sessionRootURL
            .appendingPathComponent("fixtures/documents/report.html")
            .standardizedFileURL
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            return
        }
        AgentTaskLocalWebPreviewWindowController.shared.open(
            mode: "static",
            targetUrl: htmlURL.absoluteString,
            artifactId: "validation-report",
            agentTaskId: "validation-html-live",
            sessionId: nil,
            displayName: "report.html"
        )
    }

    @objc private func submitValidationHTMLPreviewFeedback(_ sender: Any?) {
        AgentTaskLocalWebPreviewWindowController.shared.submitValidationHTMLPreviewFeedback()
    }

    @objc private func openValidationLocalServerPreviewFixture(_ sender: Any?) {
        AgentTaskLocalWebPreviewWindowController.shared.openValidationLocalServerPreview()
    }

    @objc private func openValidationLocalServerPreviewTaskFixture(_ sender: Any?) {
        // The local-server preview window and the shared AgentTaskResult
        // widget are separate WKWebViews; only the widget renders
        // ApprovalOverlay for a broadcast execution_approval_request. Open
        // it on this fixture's task so a forced live approval prompt (see
        // --force-approval-prompts) has a real, accessible Approve/Deny
        // control. Close it again with the existing "Close Managed History
        // Fixture" item -- it dismisses the same shared singleton widget
        // regardless of which fixture task it currently displays.
        AgentTaskResultWidgetController.showExistingAgentTask(agentTaskId: "validation-local-preview")
    }

    @objc private func submitValidationLocalServerPreviewFeedback(_ sender: Any?) {
        AgentTaskLocalWebPreviewWindowController.shared.submitValidationLocalServerPreviewFeedback()
    }

    @objc private func closeValidationPreviewWindow(_ sender: Any?) {
        AgentTaskLocalWebPreviewWindowController.shared.closeMostRecentValidationPreviewWindow()
    }

    @objc private func openValidationManagedHistoryFixture(_ sender: Any?) {
        // Package 5C's managed-history review panel is a normal ExecutionDetailTray
        // surface on the standard Agent Task result window, not a dedicated preview
        // window -- open it the same way the existing standalone-widget fixtures do.
        AgentTaskResultWidgetController.showExistingAgentTask(agentTaskId: "validation-managed-history")
    }

    @objc private func closeValidationManagedHistoryFixture(_ sender: Any?) {
        AgentTaskResultWidgetController.dismissShared()
    }

    @objc private func restoreValidationManagedHistoryFixture(_ sender: Any?) {
        AgentTaskResultWidgetController.requestValidationManagedHistoryRestore(
            requestId: UUID().uuidString
        )
    }

    @objc private func revealValidationSessionFolder(_ sender: Any?) {
        guard let sessionRootURL = BasilRuntimeProfile.sessionRootURL else {
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([sessionRootURL])
    }

    private func publishValidationProbe(backendAvailable: Bool) {
        guard let manifest = BasilRuntimeProfile.validationManifest else {
            return
        }
        let payload: [String: Any] = [
            "application": "Basil Validation",
            "backendAvailable": backendAvailable,
            "processIdentifier": ProcessInfo.processInfo.processIdentifier,
            "sessionID": manifest.sessionID,
            "updatedAt": ISO8601DateFormatter().string(from: Date())
        ]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            return
        }
        try? data.write(to: manifest.probeURL, options: .atomic)
    }
}
