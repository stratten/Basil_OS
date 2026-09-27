import AppKit
import Combine
import Foundation

@MainActor
final class DetachedAgentTaskWindowController: NSObject, NSWindowDelegate {
    private struct ValidationRunFocusEvidence: Codable {
        let schemaVersion: Int
        let requestId: String
        let rootTaskId: String
        let runId: String
        let requestText: String
        let resultText: String
        let documentPaths: [String]
        let artifactIds: [String]
        let previewArtifactId: String?
        let isOverviewOpen: Bool
        let observedAt: Date
    }

    private let rootTaskId: String
    private let initialFrame: NSRect
    private let onDismiss: (String) -> Void
    private var panel: NSWindow?
    private var webView: AgentTaskResultWebView?
    private var collapseController: WindowCollapseController?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private let captureOwnerID = UUID()
    private let presentationOwnerID = UUID()
    private var followUpCaptureVM: AgentTaskCaptureViewModel?
    private var followUpCancellables = Set<AnyCancellable>()

    var placementFrame: NSRect? {
        guard let panel, !panel.isMiniaturized else { return nil }
        return panel.frame
    }

    init(rootTaskId: String, initialFrame: NSRect, onDismiss: @escaping (String) -> Void) {
        self.rootTaskId = rootTaskId
        self.initialFrame = initialFrame
        self.onDismiss = onDismiss
    }

    func show() {
        let panel = CustomBorderlessWindow(
            contentRect: initialFrame,
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        panel.title = "AgentTask"
        panel.isReleasedWhenClosed = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = true
        panel.minSize = NSSize(width: 400, height: 300)
        panel.delegate = self

        let webView = AgentTaskResultWebView()
        webView.initialAgentTaskId = rootTaskId
        webView.detachedRootTaskId = rootTaskId
        webView.initiallyProcessing = false
        webView.onClose = { [weak self] in self?.dismiss() }
        webView.onMinimize = { [weak panel] in panel?.miniaturize(nil) }
        webView.onOpenDetachedAgentTask = { [weak self] rootTaskId in
            DetachedAgentTaskWindowManager.shared.open(
                rootTaskId: rootTaskId,
                originatingWindow: self?.panel
            )
        }
        webView.onOpenAgentTaskOrigin = { [weak self] originType, originId in
            AgentTaskOriginNavigator.open(
                originType: originType,
                originId: originId,
                originatingWindow: self?.panel
            )
        }
        webView.onAgentStatusChanged = { [weak self] agentTaskId, isProcessing, _, _, supportsFollowUp in
            guard let self else { return }
            AgentTaskFollowUpFocusRegistry.shared.update(
                ownerID: self.presentationOwnerID,
                agentTaskId: agentTaskId,
                isProcessing: isProcessing,
                supportsFollowUp: supportsFollowUp
            )
        }
        webView.onFocusedAgentTaskCompleted = { [weak webView] in
            guard APIClient.shared.getCachedAgentTaskSettings().autoReopenOnCompletion else { return }
            webView?.sendExpandChromeForTaskCompletion()
        }
        webView.onValidationRunFocused = { [weak self] state in
            self?.persistValidationRunFocusEvidence(state)
        }
        webView.onStartFollowUpCapture = { [weak self] rootTaskId, previousTaskId in
            self?.startFollowUpCapture(rootTaskId: rootTaskId, previousTaskId: previousTaskId)
        }
        webView.onStopFollowUpCapture = { [weak self] in
            self?.followUpCaptureVM?.completeCapture()
        }
        webView.onCancelFollowUpCapture = { [weak self] in
            self?.cancelFollowUpCapture()
        }
        webView.onResize = { [weak self, weak panel] request in
            guard let self, let panel else { return }
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
                WindowChromeCollapse.applyContentResize(window: panel, requestedSize: request.size)
            case .layout:
                if let minimumWidth = request.minimumWidth {
                    let minimumSize = NSSize(width: minimumWidth, height: 300)
                    panel.minSize = minimumSize
                    panel.contentMinSize = minimumSize
                }
                WindowChromeCollapse.applyLayoutResize(window: panel, requestedSize: request.size)
            }
        }

        panel.setFrame(initialFrame, display: true)
        panel.contentView = webView.webView
        WebKitWindowChromeAppearance.apply(to: panel)
        webView.webView.alphaValue = 0
        webView.installDragArea()
        webView.loadContent()

        self.panel = panel
        self.webView = webView
        keyboardShortcuts = WindowKeyboardShortcuts(window: panel)
        collapseController = WindowCollapseController(
            window: panel,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: initialFrame.size
        )
        AgentTaskFollowUpFocusRegistry.shared.register(ownerID: presentationOwnerID) { [weak self] rootTaskId in
            self?.startFollowUpCapture(rootTaskId: rootTaskId, previousTaskId: rootTaskId)
        }
        panel.makeKeyAndOrderFront(nil)
    }

    func bringToFront() {
        if panel?.isMiniaturized == true {
            panel?.deminiaturize(nil)
        }
        panel?.makeKeyAndOrderFront(nil)
    }

    func close() {
        panel?.close()
    }

    func requestValidationRunState(requestId: String) {
        guard isValidationRunHistoryFixture else { return }
        webView?.sendRequestValidationRunState(requestId: requestId)
    }

    func focusValidationRun(requestId: String, runId: String) {
        guard isValidationRunHistoryFixture else { return }
        webView?.sendFocusValidationRun(requestId: requestId, runId: runId)
    }

    func windowWillClose(_ notification: Notification) {
        dismiss()
    }

    func windowDidBecomeKey(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.focus(ownerID: presentationOwnerID)
    }

    func windowDidResignKey(_ notification: Notification) {
        AgentTaskFollowUpFocusRegistry.shared.resignFocus(ownerID: presentationOwnerID)
    }

    private func dismiss() {
        guard panel != nil else { return }
        cancelFollowUpCapture()
        AgentTaskFollowUpFocusRegistry.shared.unregister(ownerID: presentationOwnerID)
        panel?.delegate = nil
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
        panel?.orderOut(nil)
        panel = nil
        webView?.tearDown()
        webView = nil
        onDismiss(rootTaskId)
    }

    private func startFollowUpCapture(rootTaskId: String, previousTaskId: String?) {
        guard followUpCaptureVM == nil else { return }
        let captureVM = AgentTaskCaptureViewModel(
            rootTaskId: rootTaskId,
            previousTaskId: previousTaskId ?? rootTaskId
        )
        guard AgentTaskFollowUpCaptureLease.shared.acquire(
            ownerID: captureOwnerID,
            onComplete: { [weak captureVM] in captureVM?.completeCapture() },
            onCancel: { [weak captureVM] in captureVM?.cancelCapture() }
        ) else {
            webView?.sendCaptureStateChanged(
                type: "followUp",
                isCapturing: false,
                wordsDetected: "Another AgentTask window is recording.",
                audioLevel: 0,
                silenceProgress: 0
            )
            return
        }

        let followUpId = UUID().uuidString
        captureVM.preGeneratedAgentTaskId = followUpId
        followUpCaptureVM = captureVM
        captureVM.onCaptureComplete = { [weak self, weak captureVM] in
            guard let self else { return }
            self.finishFollowUpCapture()
            self.webView?.sendRegisterAndSelectAgent(
                agentTaskId: followUpId,
                rootTaskId: rootTaskId,
                previousTaskId: previousTaskId ?? rootTaskId
            )
            _ = captureVM
        }
        captureVM.onCaptureCanceled = { [weak self] in
            self?.finishFollowUpCapture()
        }
        // Merge the word stream with the live audio level so the detached
        // window's inline recording bubble reacts to speech instead of sitting
        // at audioLevel 0. See AgentTaskResultWidgetFollowUpCapture for the full
        // rationale.
        Publishers.CombineLatest(captureVM.$wordsDetected, captureVM.$audioLevel)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] words, level in
                self?.webView?.sendCaptureStateChanged(
                    type: "followUp",
                    isCapturing: true,
                    wordsDetected: words.joined(separator: " "),
                    audioLevel: level,
                    silenceProgress: 0
                )
            }
            .store(in: &followUpCancellables)

        webView?.sendCaptureStateChanged(
            type: "followUp",
            isCapturing: true,
            wordsDetected: "",
            audioLevel: 0,
            silenceProgress: 0
        )
        captureVM.startCapture()
    }

    private func cancelFollowUpCapture() {
        followUpCaptureVM?.cancelCapture()
        finishFollowUpCapture()
    }

    private func finishFollowUpCapture() {
        followUpCaptureVM = nil
        followUpCancellables.removeAll()
        AgentTaskFollowUpCaptureLease.shared.release(ownerID: captureOwnerID)
        webView?.sendCaptureStateChanged(
            type: "followUp",
            isCapturing: false,
            wordsDetected: "",
            audioLevel: 0,
            silenceProgress: 0
        )
    }

    private var isValidationRunHistoryFixture: Bool {
        BasilRuntimeProfile.isValidation && rootTaskId == "validation-run-history-root"
    }

    private func persistValidationRunFocusEvidence(_ state: AgentTaskValidationRunFocusState) {
        guard isValidationRunHistoryFixture,
              state.rootTaskId == rootTaskId,
              let sessionRootURL = BasilRuntimeProfile.sessionRootURL else {
            return
        }
        let evidence = ValidationRunFocusEvidence(
            schemaVersion: 1,
            requestId: state.requestId,
            rootTaskId: state.rootTaskId,
            runId: state.runId,
            requestText: state.requestText,
            resultText: state.resultText,
            documentPaths: state.documentPaths,
            artifactIds: state.artifactIds,
            previewArtifactId: state.previewArtifactId,
            isOverviewOpen: state.isOverviewOpen,
            observedAt: Date()
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        do {
            let data = try encoder.encode(evidence)
            try data.write(
                to: sessionRootURL.appendingPathComponent("run-history-focus-state.json"),
                options: .atomic
            )
        } catch {
            DevLogger.shared.error(
                "Failed to persist validation run-focus evidence: \(error.localizedDescription)",
                context: "AgentTaskResult"
            )
        }
    }
}
