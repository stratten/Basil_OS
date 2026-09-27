import AppKit
import Combine

/// Snapshot of a setup-launched AssistantSession's terminal state, captured
/// from the view model's published properties at the moment the session
/// transitions out of `.running`. Passed back to the launching caller (the
/// setup-assistant bridge) so it can convert it into an execution_outcomes
/// turn for the setup agent to react to.
///
/// `sessionId` is optional because a session that fails before the backend
/// allocates an id (e.g., the `start_from_text` POST itself fails) still
/// produces a terminal transition the caller deserves to know about — just
/// without an id to key tracking on.
struct SetupAssistantSessionTerminalOutcome {
    let sessionId: String?
    /// "completed" or "failed" — mirrors the wire vocabulary the
    /// setup-agent observation handler already understands for agent tasks.
    let status: String
    let resultText: String?
    let errorMessage: String?
}

// Progress status for the AssistantSession workflow
public enum ProgressStatus {
    case starting
    case initializing
    case waitingForModel
    case uploadingAudio
    case ocrComplete
    case ocrFailed
    case transcriptionComplete
    case transcriptionFailed
    case processing
    case complete
    case error
}

final class AssistantSessionWindowController: NSWindowController, NSWindowDelegate, AppearanceRefreshable {
    public static var sharedController: AssistantSessionWindowController?
    fileprivate var webView: AssistantSessionWebView?
    fileprivate var bridgeController: AssistantSessionBridgeController?
    internal let viewModel: AssistantSessionViewModel
    private var cancellables = Set<AnyCancellable>()
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var lastAutomaticResizeTarget: NSSize?

    init(window: NSWindow, viewModel: AssistantSessionViewModel) {
        self.viewModel = viewModel
        super.init(window: window)
        
        // Subscribe to idealSizeUpdateRequest from ViewModel
        viewModel.idealSizeUpdateRequest
            .receive(on: DispatchQueue.main)
            .sink { [weak self] newSize in
                self?.resizeWindow(to: newSize)
            }
            .store(in: &cancellables)
        
        // Observe auto-close requests for AssistantSession widget
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleCloseRequest(_:)),
            name: NSNotification.Name("CloseAssistantSessionWidgetRequest"),
            object: nil
        )
        
        // Set up keyboard shortcuts (Cmd+W to close, Cmd+M to minimize)
        keyboardShortcuts = WindowKeyboardShortcuts(window: window)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    static func show() {
        let viewModel = AssistantSessionViewModel()
        #if DEBUG
        DevLogger.shared.info("🪟 AssistantSessionWindowController.show() called", context: "AssistantSessionWindowController")
        #endif
        if let existing = sharedController {
            existing.window?.level = .floating
            // If window is minimized, deminiaturize it first
            if existing.window?.isMiniaturized == true {
                existing.window?.deminiaturize(nil)
            }
            existing.window?.orderFront(nil)
            return
        }
        presentWindow(with: viewModel)
    }

    /// Present the AssistantSession widget for a setup-launched (Dill)
    /// session and auto-fire the request — no manual Submit click.
    ///
    /// Previously this method only seeded view-model state and returned,
    /// requiring the user to click Submit (which was additionally grayed
    /// out when `ocrText` was nil). The new behavior matches the setup
    /// `launch_agent_task` story: present the window, give the web surface a beat
    /// to mount, then invoke `startAssistantSessionFlowFromSetup` which
    /// allocates a no-OCR session and drives the typed-instruction upload
    /// directly. The button-grayed-out problem dissolves two ways: (a)
    /// the view-model flow seeds `ocrText` to `contextText` so `canSubmit`
    /// is true, and (b) auto-fire means the button is never the
    /// load-bearing path anyway.
    ///
    /// `modelId`, when provided, is forwarded so the launched session
    /// inherits the setup agent's chosen route (e.g., the free-proxy
    /// model setup itself is running on) instead of silently falling
    /// back to the user's preferred reasoning model.
    ///
    /// The two optional callbacks let the launching caller (the
    /// setup-assistant bridge) observe the session's lifecycle without
    /// reaching into the view model directly:
    ///
    /// - `onSessionStarted(sessionId)` fires once, the moment the
    ///   view model finishes allocating a backend session id and
    ///   transitions into `.running`. The bridge uses this signal to
    ///   resolve its pending action-result with `assistantSessionId` so
    ///   the frontend can register the session for re-engagement.
    /// - `onSessionTerminal(outcome)` fires once when the session
    ///   transitions out of `.running` into a terminal state
    ///   (`.completed` or `.failed`). The bridge uses this signal to
    ///   emit a `setupAssistantAssistantSessionObservation` custom event
    ///   so the setup agent can narrate the outcome and propose
    ///   follow-ups — symmetric to the launch_agent_task flow.
    ///
    /// Both callbacks are wired via a single Combine `.sink` on the
    /// view model's `$assistantSessionStatus`. Status mutations all
    /// happen on the main actor, and `sessionId` is always assigned
    /// before the `.running` transition (see
    /// `startAssistantSessionFlowFromSetup`), so reading `sessionId`
    /// inside the `.running` branch is race-free. The sink is stored
    /// on the freshly-created controller's `cancellables` so its
    /// lifetime is bounded by the window's.
    @MainActor
    static func showFromSetupAssistant(
        instruction: String,
        contextText: String?,
        applicationName: String?,
        modelId: String? = nil,
        onSessionStarted: ((String) -> Void)? = nil,
        onSessionTerminal: ((SetupAssistantSessionTerminalOutcome) -> Void)? = nil
    ) {
        if let existing = sharedController {
            existing.window?.close()
        }

        let viewModel = AssistantSessionViewModel()
        viewModel.detectedApplicationName = applicationName ?? "Setup Assistant"
        viewModel.shouldPersistUI = true
        viewModel.publishWidgetSizeForCurrentModality()
        presentWindow(with: viewModel)

        // Wire setup-launch lifecycle observation into the freshly-created
        // controller's Combine bag. The bag lives on the controller, so the
        // subscription is automatically torn down when the window closes
        // and `windowWillClose` clears `sharedController`. We capture
        // small `hasFired*` latches in the closure so each callback runs
        // exactly once even if `assistantSessionStatus` happens to
        // re-publish the same terminal value (Combine semantics on
        // `@Published` deliver every assignment, not only distinct ones).
        if let controller = sharedController,
           onSessionStarted != nil || onSessionTerminal != nil {
            var hasFiredStarted = false
            var hasFiredTerminal = false
            viewModel.$assistantSessionStatus
                .dropFirst() // skip the .idle replay we get for free on subscribe
                .sink { [weak viewModel] status in
                    guard let viewModel else { return }
                    switch status {
                    case .running:
                        guard !hasFiredStarted else { return }
                        hasFiredStarted = true
                        // `sessionId` is set synchronously on the main actor
                        // immediately before status flips to .running inside
                        // startAssistantSessionFlowFromSetup, so it is
                        // guaranteed to be populated here on the success
                        // path. We still guard nil/empty so a future flow
                        // that flips to .running without an id fails quietly
                        // rather than dispatching a malformed signal.
                        if let sessionId = viewModel.sessionId,
                           !sessionId.isEmpty {
                            onSessionStarted?(sessionId)
                        }
                    case .completed, .failed:
                        guard !hasFiredTerminal else { return }
                        hasFiredTerminal = true
                        // Prefer the formal `assistantOutput` field — it is
                        // the final, post-stream snapshot the widget shows
                        // to the user. Fall back to `combinedResult` for
                        // failure modes where the stream ended mid-way and
                        // the final commit never happened.
                        let resolvedResult = !viewModel.assistantOutput.isEmpty
                            ? viewModel.assistantOutput
                            : viewModel.combinedResult
                        let outcome = SetupAssistantSessionTerminalOutcome(
                            sessionId: viewModel.sessionId,
                            status: status == .completed ? "completed" : "failed",
                            resultText: resolvedResult.isEmpty ? nil : resolvedResult,
                            errorMessage: viewModel.errorMessage
                        )
                        onSessionTerminal?(outcome)
                    case .idle:
                        break
                    }
                }
                .store(in: &controller.cancellables)
        }

        // Brief delay so the web surface has time to mount the widget hierarchy
        // before we mutate the view model's state and start the upload
        // task. Mirrors the rehydrated path's 150ms mount delay so the
        // UI shows the seeded state and the streaming output without
        // a visible flicker.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 150_000_000)
            await viewModel.startAssistantSessionFlowFromSetup(
                instruction: instruction,
                contextText: contextText ?? "",
                modelId: modelId
            )
        }
    }

    /// Open the AssistantSession widget pre-loaded with a rehydrated AssistantSession
    /// output from history, then immediately enter refinement mode and
    /// start recording.
    ///
    /// The backend has already created a fresh in-memory assistantSession
    /// session keyed by `resume.sessionId`; we wire that session id into
    /// the view model and seed the published state so the widget renders
    /// the `.result` branch. Because the user explicitly chose "Refine"
    /// on the history item, we skip the second click on the in-widget
    /// Refine button and dispatch straight into `enterRefinementMode()`
    /// + `startRefinementRecording()` once the window is mounted.
    ///
    /// If a AssistantSession widget is already open (possibly mid-stream on a
    /// different session), it is closed first so we never mix two
    /// sessions in one view model.
    @MainActor
    static func show(rehydratedFrom resume: AssistantSessionRehydrateResponse) {
        #if DEBUG
        DevLogger.shared.info(
            "🪟 AssistantSessionWindowController.show(rehydratedFrom:) called for session=\(resume.sessionId), assistant_output_id=\(resume.assistantOutputId)",
            context: "AssistantSessionWindowController"
        )
        #endif

        // If a widget is already up, close it so we don't conflate two sessions
        // in one VM. windowWillClose() clears `sharedController` for us.
        if let existing = sharedController {
            existing.window?.close()
        }

        let viewModel = AssistantSessionViewModel()
        applyRehydratedState(resume, to: viewModel)

        // Use the heuristic-computed ideal size as the explicit initial frame.
        // Preserve the explicit initial frame so the rehydrated window lands at
        // the view model's computed size before the web surface reports updates.
        let initialContentSize = NSSize(
            width: viewModel.currentIdealWidgetWidth,
            height: viewModel.currentIdealWidgetHeight
        )
        presentWindow(with: viewModel, initialContentSize: initialContentSize)

        // Auto-start refinement recording. The view model's onAppear-driven
        // initialization runs on the main actor; yield one runloop turn so the
        // hosting view has mounted and the audio capture service is wired up
        // before we ask it to record.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 150_000_000)
            viewModel.enterRefinementMode()
            await viewModel.startRefinementRecording()
        }
    }

    /// Seed a fresh view model with rehydrated state so the widget lands in
    /// `.result` (completed) immediately.
    ///
    /// `updateIdealSizes(shouldPersist: true)` is invoked directly here rather
    /// than waiting for the web surface's initial resize report. Calling the
    /// heuristic explicitly populates `currentIdealWidgetWidth` /
    /// `currentIdealWidgetHeight` so the controller can place the window at
    /// the right size on the very first display.
    @MainActor
    private static func applyRehydratedState(
        _ resume: AssistantSessionRehydrateResponse,
        to viewModel: AssistantSessionViewModel
    ) {
        viewModel.sessionId = resume.sessionId
        viewModel.assistantOutput = resume.outputText
        viewModel.transcriptionText = resume.userRequest ?? ""
        viewModel.ocrText = resume.contextText
        viewModel.assistantSessionStatus = .completed
        viewModel.transcriptionStatus = .completed
        viewModel.ocrStatus = .completed
        viewModel.errorMessage = nil
        viewModel.shouldPersistUI = true
        viewModel.updateIdealSizes(shouldPersist: true)
    }

    /// Create and display the widget window.
    ///
    /// - Parameter initialContentSize: When provided, used directly as the
    ///   initial content size — required for the rehydrated path because
    ///   pre-populated content makes `contentView.fittingSize` blow out
    ///   horizontally. When nil (the default empty-start flow), falls back
    ///   to `contentView.fittingSize`, which is sane for an empty VM.
    @MainActor
    private static func presentWindow(
        with viewModel: AssistantSessionViewModel,
        initialContentSize: NSSize? = nil
    ) {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 138), // Reduced height from 320 to 220 to match actual content needs
            styleMask: [.borderless, .resizable, .miniaturizable], // Borderless like AgentTaskCapture
            backing: .buffered,
            defer: false
        )
        
        // Configure borderless window properties
        window.level = .floating
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]
        window.hidesOnDeactivate = false
        window.hasShadow = false // Widget has its own shadow
        window.alphaValue = 1.0
        window.isOpaque = false
        window.backgroundColor = NSColor.clear
        window.isMovableByWindowBackground = true  // Allow dragging the window by its background

        let controller = AssistantSessionWindowController(window: window, viewModel: viewModel)
        let webView = AssistantSessionWebView()
        window.contentView = webView.webView
        controller.webView = webView
        let bridgeController = AssistantSessionBridgeController(viewModel: viewModel, output: webView)
        controller.bridgeController = bridgeController
        AppearanceRefreshCoordinator.shared.register(controller)
        webView.onIntent = { [weak bridgeController] intent in bridgeController?.handle(intent: intent) }
        webView.onModelPickerSelection = { [weak bridgeController] modelId in
            bridgeController?.handle(intent: ["type": "selectModel", "modelId": modelId])
        }
        webView.onResize = { [weak controller] width, height in
            controller?.resizeWindow(to: (width: width, height: height))
        }
        webView.onReady = { [weak bridgeController] in bridgeController?.sendInitialSnapshot() }
        controller.installDragArea(in: webView)
        webView.loadContent()
        let resolvedContentSize = initialContentSize ?? NSSize(width: 300, height: 138)

        sharedController = controller
        window.delegate = controller
        
        // Set up minimize callback
        viewModel.onMinimize = { [weak window] in
            window?.miniaturize(nil)
        }
        
        // Apply rounded corners to borderless window after content view is set
        controller.setupBorderlessAppearance(for: window)

        var desiredFrame = window.frameRect(forContentRect: NSRect(origin: .zero, size: resolvedContentSize))
        if let screen = NSScreen.main {
            let screenFrame = screen.visibleFrame
            desiredFrame.origin.x = screenFrame.maxX - desiredFrame.size.width - 20 // 20px margin from edge
            desiredFrame.origin.y = screenFrame.maxY - desiredFrame.size.height - 20 // 20px margin from top
        } else {
            // Fallback to current frame origin if no screen available
            desiredFrame.origin = window.frame.origin
        }
        window.setFrame(desiredFrame, display: false, animate: false)
        
        window.orderFront(nil)
        #if DEBUG
        DevLogger.shared.info("🪟 AssistantSessionWindowController created and borderless window shown", context: "AssistantSessionWindowController")
        #endif
    }

    private func installDragArea(in assistantSessionWebView: AssistantSessionWebView, headerHeight: CGFloat = 44) {
        let dragView = WindowDragAreaView(leadingInteractiveWidth: 88, trailingInteractiveWidth: 56)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        assistantSessionWebView.webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: assistantSessionWebView.webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: assistantSessionWebView.webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: assistantSessionWebView.webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: headerHeight),
        ])
    }

    func showProgress(status: ProgressStatus) {
        self.updateProgress(status: status)
    }

    func updateProgress(status: ProgressStatus) {
        DispatchQueue.main.async {
            switch status {
            case .starting, .initializing:
                self.viewModel.ocrStatus = .running
                self.viewModel.errorMessage = nil
            case .waitingForModel, .uploadingAudio, .ocrComplete:
                self.viewModel.ocrStatus = .completed
            case .ocrFailed:
                self.viewModel.ocrStatus = .failed
            case .transcriptionComplete:
                self.viewModel.transcriptionStatus = .completed
            case .transcriptionFailed:
                self.viewModel.transcriptionStatus = .failed
            case .processing:
                // No-op or set a custom property if needed
                break
            case .complete:
                // No-op or set a custom property if needed
                break
            case .error:
                self.viewModel.errorMessage = "An error occurred during AssistantSession."
            }
        }
    }

    func refreshAppearance() {
        bridgeController?.sendThemeChanged()
    }

    func windowWillClose(_ notification: Notification) {
        #if DEBUG
        DevLogger.shared.info("🪟 AssistantSessionWindowController.windowWillClose called", context: "AssistantSessionWindowController")
        #endif
        if AssistantSessionWindowController.sharedController === self {
            AssistantSessionWindowController.sharedController = nil
        }
        // No resetStatuses() call; just stop recording and clear error if needed
        viewModel.audioCaptureService.stopRecording(sendAudioData: false)
        _ = viewModel.audioCaptureService.lastRecordingData
        viewModel.errorMessage = nil
        #if DEBUG
        DevLogger.shared.info("🪟 AssistantSessionWindowController: cleanupAfterRun called on viewModel", context: "AssistantSessionWindowController")
        #endif
        // Remove observer when window closes
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("CloseAssistantSessionWidgetRequest"), object: nil)
        AppearanceRefreshCoordinator.shared.unregister(self)
        
        // Clean up keyboard shortcuts
        keyboardShortcuts?.cleanup()
        keyboardShortcuts = nil
    }

    @objc private func handleCloseRequest(_ notification: Notification) {
        #if DEBUG
        DevLogger.shared.info("Auto-close request received, closing AssistantSession window", context: "AssistantSessionWindowController")
        #endif
        self.window?.close()
    }

    private func resizeWindow(to newSize: (width: CGFloat, height: CGFloat)) {
        guard let window = self.window else { return }
        let currentFrame = window.frame
        let visibleFrame = (window.screen ?? NSScreen.main)?.visibleFrame
        let horizontalMargin: CGFloat = 20
        let verticalMargin: CGFloat = 20
        let newWidth = min(newSize.width, max(1, (visibleFrame?.width ?? newSize.width) - (horizontalMargin * 2)))
        let newHeight = min(newSize.height, max(1, (visibleFrame?.height ?? newSize.height) - (verticalMargin * 2)))
        let targetSize = NSSize(width: newWidth, height: newHeight)

        guard lastAutomaticResizeTarget.map({ abs($0.width - targetSize.width) > 0.5 || abs($0.height - targetSize.height) > 0.5 }) ?? true else {
            return
        }
        lastAutomaticResizeTarget = targetSize

        let oldHeight = currentFrame.height
        let oldWidth = currentFrame.width
        guard abs(oldWidth - newWidth) > 0.5 || abs(oldHeight - newHeight) > 0.5 else { return }

        // Calculate new origin to keep the top-right corner stationary
        // This makes the window expand leftward while staying anchored to the top-right
        var newOriginX = currentFrame.origin.x + oldWidth - newWidth
        var newOriginY = currentFrame.origin.y + oldHeight - newHeight
        if let visibleFrame {
            newOriginX = min(max(newOriginX, visibleFrame.minX + horizontalMargin), visibleFrame.maxX - newWidth - horizontalMargin)
            newOriginY = min(max(newOriginY, visibleFrame.minY + verticalMargin), visibleFrame.maxY - newHeight - verticalMargin)
        }

        let newFrame = NSRect(x: newOriginX, y: newOriginY, width: newWidth, height: newHeight)
        
        #if DEBUG
        DevLogger.shared.info("🪟 AssistantSessionWindowController attempting to resize window. Current: \(currentFrame), New: \(newFrame)", context: "AssistantSessionWindowController")
        #endif
        
        window.setFrame(newFrame, display: true, animate: true)
    }
    
    // MARK: - Private Methods
    private func setupBorderlessAppearance(for window: NSWindow) {
        #if DEBUG
        DevLogger.shared.info("Setting up borderless appearance with rounded corners for AssistantSession", context: "AssistantSessionWindowController")
        #endif
        
        window.backgroundColor = .clear
        window.hasShadow = false
        window.isOpaque = false
        
        if let contentView = window.contentView {
            contentView.wantsLayer = true
            contentView.layer?.cornerRadius = 16 // Match widget's corner radius
            contentView.layer?.masksToBounds = false // Allow custom shadow/border layers to render
        }
    }
} 