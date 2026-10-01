
import AppKit
import Combine
import Foundation
import SwiftUI

private struct AgentTaskCaptureModelPickerPopover: View {
    let models: [CaptureModelPickerOption]
    let selectedModelId: String?
    let onSelection: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                modelSection("Local Models", category: "local")
                if models.contains(where: { $0.category == "local" }) && models.contains(where: { $0.category != "local" }) {
                    Divider()
                        .overlay(AestheticSystem.Colors.secondary.opacity(0.18))
                        .padding(.vertical, 5)
                }
                modelSection("API Models", category: "api")
                modelSection("Custom Models", category: "custom")
            }
            .padding(5)
        }
        .background(AestheticSystem.Colors.backgroundPrimary)
    }

    @ViewBuilder
    private func modelSection(_ title: String, category: String) -> some View {
        let sectionModels = models.filter { $0.category == category }
        if !sectionModels.isEmpty {
            Text(title)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(AestheticSystem.Colors.textSecondary)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
            ForEach(sectionModels, id: \.id) { model in
                Button {
                    onSelection(model.id)
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark")
                            .font(.system(size: 9, weight: .semibold))
                            .opacity(model.id == selectedModelId ? 1 : 0)
                        Text(model.displayName)
                            .font(.system(size: 10))
                            .foregroundColor(AestheticSystem.Colors.textPrimary)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 7)
                    .padding(.vertical, 5)
                    .background(
                        RoundedRectangle(cornerRadius: 4)
                            .fill(model.id == selectedModelId ? AestheticSystem.Colors.primary.opacity(0.1) : .clear)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

@MainActor
final class AgentTaskCaptureInputWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    static weak var activeController: AgentTaskCaptureInputWindowController?

    /// Internal (not `private`), matching `AgentTaskCaptureWindowController.panel`'s
    /// access level exactly: `AppDelegate_ScheduledRunMiniPanel.swift` reads
    /// `AgentTaskCaptureWindowController.activeController?.panel?.frame` as an
    /// anchor for positioning the scheduled-run mini panel relative to an
    /// in-flight capture widget. See `09_Swift_Modified_Files_Exact_Edits.md`
    /// for that call site's required type-name edit.
    var panel: NSWindow?
    private var viewModel: AgentTaskCaptureViewModel?
    private var hostWebView: AgentTaskCaptureInputWebView?
    private var cancellables = Set<AnyCancellable>()
    private var localKeyMonitor: Any?
    private var referenceFilePicker: NSOpenPanel?
    private var modelPickerPopover: NSPopover?

    private var snapshotRevision = 0
    private var audioRevision = 0
    private var isDraggingOver = false
    private var lastCaptureWidgetFrame: NSRect?
    /// Set only from a genuine live user drag-resize in `windowDidResize`
    /// (never from our own `resizeWindow(to:)` calls, guarded by
    /// `isApplyingProgrammaticResize`). Content-driven resize requests are
    /// floored against this so dropping a file, adding/removing a
    /// reference path, or switching modality never shrinks the window
    /// below a size the user deliberately dragged it to.
    private var userExpandedSize: NSSize?
    /// True for the duration of a programmatic `resizeWindow(to:)` call,
    /// including its animation, so `windowDidResize` — whose top-right
    /// anchoring is meant only for live user drag-resizes — does not fight
    /// the animation using stale intermediate frame sizes.
    private var isApplyingProgrammaticResize = false
    private var didNotifyBackendWidgetClosed = false

    var isVisible: Bool { panel != nil }

    // Kept in sync with `AgentTaskCaptureViewModel.CapturePanelLayout` by
    // hand (see that enum's doc comment) — this is the *initial* size at
    // `show()` time, before the view model's own `sizeUpdateRequest` takes
    // over for reference-path/mode-driven resizes.
    private static let voiceModeSize = NSSize(
        width: AgentTaskCaptureViewModel.CapturePanelLayout.voiceWidth,
        height: AgentTaskCaptureViewModel.CapturePanelLayout.voiceBaseHeight
    )
    private static let textModeSize = NSSize(
        width: AgentTaskCaptureViewModel.CapturePanelLayout.textWidth,
        height: AgentTaskCaptureViewModel.CapturePanelLayout.textBaseHeight
    )
    private static let screenMargin: CGFloat = 20

    static func nativeModelPickerPopoverContentSize(forModelCount modelCount: Int) -> NSSize {
        NSSize(width: 210, height: min(260, max(70, 34 + (modelCount * 28))))
    }

    static func initialCaptureSetup(
        preGeneratedAgentTaskId: String?,
        modality: AgentTaskInputModality
    ) -> (agentTaskId: String, windowSize: NSSize) {
        (
            agentTaskId: preGeneratedAgentTaskId ?? UUID().uuidString,
            windowSize: modality == .text ? textModeSize : voiceModeSize
        )
    }

    // MARK: - Show / Hide

    func show(preGeneratedAgentTaskId: String? = nil) {
        guard panel == nil else { return }

        let defaultModality = APIClient.shared.getCachedAgentTaskSettings().modality
        let initialSetup = Self.initialCaptureSetup(
            preGeneratedAgentTaskId: preGeneratedAgentTaskId,
            modality: defaultModality
        )
        let viewModel = AgentTaskCaptureViewModel()
        viewModel.preGeneratedAgentTaskId = initialSetup.agentTaskId
        viewModel.pendingInitialModality = defaultModality
        self.viewModel = viewModel

        let hostWebView = AgentTaskCaptureInputWebView()
        self.hostWebView = hostWebView

        let initialSize = initialSetup.windowSize
        let newPanel = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: initialSize.width, height: initialSize.height),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        newPanel.title = BasilTeamIdentity.agentTask.displayName
        newPanel.level = .floating
        newPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        newPanel.isReleasedWhenClosed = false
        newPanel.hidesOnDeactivate = false
        newPanel.hasShadow = false
        newPanel.alphaValue = 1.0
        newPanel.isOpaque = false
        newPanel.backgroundColor = .clear
        newPanel.isMovableByWindowBackground = true
        newPanel.minSize = initialSize
        newPanel.contentMinSize = initialSize
        newPanel.delegate = self
        newPanel.contentView = hostWebView.webView
        newPanel.appearance = NSAppearance(named: .aqua)

        panel = newPanel
        Self.activeController = self

        wireViewModelCallbacks(viewModel)
        wireWebViewCallbacks(hostWebView, viewModel: viewModel)
        subscribeToViewModelChanges(viewModel)
        AppearanceRefreshCoordinator.shared.register(self)
        setupWindowCommandShortcuts(for: newPanel)

        hostWebView.loadContent()
        positionPanel(newPanel)
        lastCaptureWidgetFrame = newPanel.frame
        userExpandedSize = nil
        newPanel.makeKeyAndOrderFront(nil)

        viewModel.startCapture()
    }

    func hide() {
        viewModel?.cancelCapture()
        // `cancelCapture()` intentionally no-ops after completion. Always perform the close fallback so a programmatic hide cannot leave a completed capture panel stranded during its handoff delay.
        hideWithoutCanceling()
    }

    private func hideWithoutCanceling() {
        guard panel != nil || viewModel != nil || hostWebView != nil else { return }
        let associatedAgentTaskId = viewModel?.preGeneratedAgentTaskId
        notifyBackendWidgetClosedIfNeeded(agentTaskId: associatedAgentTaskId)
        cleanupWindowCommandShortcuts()
        referenceFilePicker?.cancel(nil)
        referenceFilePicker = nil
        modelPickerPopover?.performClose(nil)
        modelPickerPopover = nil
        cancellables.removeAll()
        AppearanceRefreshCoordinator.shared.unregister(self)
        panel?.orderOut(nil)
        panel?.delegate = nil
        panel = nil
        hostWebView?.tearDown()
        hostWebView = nil
        viewModel = nil
        if Self.activeController === self {
            Self.activeController = nil
        }
    }

    /// Public entry point mirroring `AgentTaskCaptureWindowController.cancelActiveCapture()`,
    /// used by the same restricted call sites (hotkey re-press, wake-word
    /// cancellation path).
    func cancelActiveCapture() {
        viewModel?.cancelCapture()
    }

    /// Identical to `AgentTaskCaptureWindowController.anyCaptureViewModel`
    /// (dossier-adjacent oracle property, confirmed at
    /// `AgentTaskCaptureWindowController.swift` lines 229-232). Read by
    /// `WebSocketService_AgentTask.handleAgentTaskStarted(json:)`'s GATE 1
    /// wake-word "is anything capturing right now" check — see
    /// `09_Swift_Modified_Files_Exact_Edits.md` for that call site's
    /// required type-name edit.
    var anyCaptureViewModel: AgentTaskCaptureViewModel? {
        if let vm = viewModel, vm.isCapturing { return vm }
        return nil
    }

    // MARK: - View model wiring

    private func wireViewModelCallbacks(_ viewModel: AgentTaskCaptureViewModel) {
        viewModel.onCaptureComplete = { [weak self] in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.handoffToResultWidget()
            }
        }
        viewModel.onCaptureCanceled = { [weak self] in
            self?.hideWithoutCanceling()
        }
        viewModel.sizeUpdateRequest
            .receive(on: DispatchQueue.main)
            .sink { [weak self] newSize in
                self?.resizeWindow(to: newSize)
            }
            .store(in: &cancellables)
    }

    /// Combine bridge from the oracle view model's `@Published` properties to
    /// the wire's full-`CaptureSnapshot` channel. Throttled 50ms so a burst
    /// of rapid changes (e.g. word-detection updates arriving faster than
    /// the UI needs to redraw) coalesces into one push, matching the
    /// migration guide's "coalesced" requirement without needing a partial-
    /// delta merge scheme (`05_Bridge_Contract_And_Types.md` section 5.4,
    /// decision 10 in `00_README_And_Execution_Order.md`).
    private func subscribeToViewModelChanges(_ viewModel: AgentTaskCaptureViewModel) {
        viewModel.objectWillChange
            .throttle(for: .milliseconds(50), scheduler: DispatchQueue.main, latest: true)
            .sink { [weak self] _ in
                // ObservableObject publishes before the property mutation. Move snapshot construction to the next main-queue turn so React receives the committed values rather than the prior state.
                DispatchQueue.main.async { [weak self] in
                    self?.pushSnapshot()
                }
            }
            .store(in: &cancellables)

        viewModel.$audioLevel
            .throttle(for: .milliseconds(50), scheduler: DispatchQueue.main, latest: true)
            .sink { [weak self] level in
                self?.pushAudioLevel(level)
            }
            .store(in: &cancellables)

    }

    func refreshAppearance() {
        hostWebView?.sendThemeChanged()
        hostWebView?.sendFontsChanged()
    }

    private func pushSnapshot() {
        guard let viewModel, let hostWebView else { return }
        snapshotRevision += 1
        let snapshot = CaptureSnapshot.from(
            viewModel: viewModel,
            isDraggingOver: isDraggingOver,
            revision: snapshotRevision
        )
        hostWebView.sendSnapshot(snapshot)
    }

    private func pushAudioLevel(_ level: Float) {
        guard let hostWebView else { return }
        audioRevision += 1
        hostWebView.sendAudioLevel(level, audioRevision: audioRevision)
    }

    // MARK: - Web view wiring

    private func wireWebViewCallbacks(_ hostWebView: AgentTaskCaptureInputWebView, viewModel: AgentTaskCaptureViewModel) {
        hostWebView.onReactReady = { [weak self, weak viewModel] in
            guard let self, let viewModel else { return }
            self.snapshotRevision += 1
            let snapshot = CaptureSnapshot.from(
                viewModel: viewModel,
                isDraggingOver: self.isDraggingOver,
                revision: self.snapshotRevision
            )
            hostWebView.sendInit(port: APIClient.shared.currentPort, snapshot: snapshot)
        }

        hostWebView.onMessage = { [weak self, weak viewModel] intent in
            guard let self, let viewModel else { return }
            self.handle(intent, viewModel: viewModel)
        }

        hostWebView.onFilesDropped = { [weak viewModel] urls in
            viewModel?.addReferencePaths(urls)
        }
    }

    private func handle(_ intent: CaptureInputMessage, viewModel: AgentTaskCaptureViewModel) {
        switch intent {
        case .captureInputReady, .unknown:
            return // Handled in AgentTaskCaptureInputWebView.handleMessage directly.
        case .requestSnapshot:
            pushSnapshot()
        case .requestCaptureResize(let width, let height):
            resizeWindow(to: (width: width, height: height))
        case .captureHeaderExtent(let height):
            hostWebView?.updateDragAreaHeight(height)
        case .enterVoiceMode:
            viewModel.enterVoiceMode()
        case .enterTextEntryMode:
            viewModel.enterTextEntryMode()
        case .updateTextDraft(let text):
            viewModel.textPrompt = text
        case .submitTextPrompt(let text, let modelId):
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  !viewModel.isSubmittingTextPrompt,
                  !viewModel.hasCompleted else {
                return
            }
            viewModel.textPrompt = text
            viewModel.selectedAgentTaskModelId = modelId
            viewModel.isSubmittingTextPrompt = true
            Task { await viewModel.submitTextPrompt(modelId: modelId) }
        case .setSelectedModel(let modelId):
            viewModel.selectedAgentTaskModelId = modelId
        case .showNativeModelPicker(let models, let selectedModelId, let anchorRect):
            presentNativeModelPicker(models: models, selectedModelId: selectedModelId, anchorRect: anchorRect, viewModel: viewModel)
        case .cancelCapture:
            hide()
        case .pickReferenceFiles:
            presentReferenceFilePicker(viewModel: viewModel)
        case .removeReferencePath(let index):
            viewModel.removeReferencePath(at: index)
        case .openReferencePath(let path):
            guard viewModel.referencePaths.contains(where: { $0.path == path }) else { return }
            NSWorkspace.shared.open(URL(fileURLWithPath: path))
        case .filesDropped(let paths):
            viewModel.addReferencePaths(paths.map { URL(fileURLWithPath: $0) })
        case .setDraggingOver(let value):
            isDraggingOver = value
            pushSnapshot()
        case .showHistory:
            AgentTaskResultWidgetController.showStandaloneHistory(anchorFrame: panel?.frame)
        }
    }

    /// Identical `NSOpenPanel` configuration to `AgentTaskCaptureWidget.swift`'s
    /// `openFilePicker()` (dossier section 1.5), reused verbatim.
    private func presentReferenceFilePicker(viewModel: AgentTaskCaptureViewModel) {
        guard referenceFilePicker == nil else { return }
        let openPanel = NSOpenPanel()
        openPanel.allowsMultipleSelection = true
        openPanel.canChooseFiles = true
        openPanel.canChooseDirectories = true
        openPanel.canCreateDirectories = false
        openPanel.title = "Attach Files or Folders"
        referenceFilePicker = openPanel
        openPanel.begin { [weak self, weak viewModel] response in
            self?.referenceFilePicker = nil
            guard response == .OK, !openPanel.urls.isEmpty else { return }
            DispatchQueue.main.async {
                viewModel?.addReferencePaths(openPanel.urls)
            }
        }
    }

    private func presentNativeModelPicker(
        models: [CaptureModelPickerOption],
        selectedModelId: String?,
        anchorRect: CaptureModelPickerAnchorRect,
        viewModel: AgentTaskCaptureViewModel
    ) {
        guard self.viewModel === viewModel, let webView = hostWebView?.webView else { return }
        guard !models.isEmpty else { return }
        modelPickerPopover?.performClose(nil)
        let popover = NSPopover()
        popover.behavior = .transient
        popover.appearance = NativeModelPickerPopoverSupport.themedAppearance()
        popover.contentSize = Self.nativeModelPickerPopoverContentSize(forModelCount: models.count)
        popover.contentViewController = NSHostingController(
            rootView: AgentTaskCaptureModelPickerPopover(
                models: models,
                selectedModelId: selectedModelId,
                onSelection: { [weak self, weak popover, weak viewModel] modelId in
                    popover?.performClose(nil)
                    viewModel?.selectedAgentTaskModelId = modelId
                    self?.modelPickerPopover = nil
                }
            )
        )
        modelPickerPopover = popover
        let fallbackAnchor = NativeModelPickerPopoverSupport.anchorRect(
            webX: anchorRect.x,
            webY: anchorRect.y,
            width: anchorRect.width,
            height: anchorRect.height,
            hostBounds: webView.bounds,
            hostIsFlipped: webView.isFlipped
        )
        let anchor: NSRect
        if let window = webView.window {
            let pointInWindow = window.convertPoint(fromScreen: NSEvent.mouseLocation)
            let pointInWebView = webView.convert(pointInWindow, from: nil)
            anchor = NSRect(x: pointInWebView.x, y: pointInWebView.y, width: 1, height: 1)
        } else {
            anchor = fallbackAnchor
        }
        popover.show(relativeTo: anchor, of: webView, preferredEdge: .minY)
        NativeModelPickerPopoverSupport.paintThemedFrameBackground(of: popover)
    }

    // MARK: - Handoff to result widget

    /// Identical call shape to `AgentTaskCaptureWindowController.handoffToResultWidget()`
    /// (dossier section 1.8), reusing `AgentTaskResultPresentationRouter`
    /// unmodified — this is the single point where the new capture flow
    /// hands off to the existing, untouched result-widget presentation.
    private func handoffToResultWidget() {
        guard let viewModel else {
            hideWithoutCanceling()
            return
        }
        let agentTaskId = viewModel.preGeneratedAgentTaskId ?? UUID().uuidString
        let initialAgentTask: String? = viewModel.isTextEntryMode
            ? viewModel.textPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
            : nil
        let captureFrame = panel?.frame ?? lastCaptureWidgetFrame
        AgentTaskResultPresentationRouter.installNewAgent(
            agentTaskId: agentTaskId,
            initialAgentTask: initialAgentTask,
            placement: captureFrame.map { .topRightScreenContainingFrame($0) } ?? .topRightCurrentScreen,
            initialReferencePaths: viewModel.referencePaths
        )
        hideWithoutCanceling()
    }

    // MARK: - Positioning / Resizing

    private func positionPanel(_ panel: NSWindow) {
        let currentScreen = NSScreen.screens.first { screen in
            NSMouseInRect(NSEvent.mouseLocation, screen.frame, false)
        } ?? NSScreen.main
        guard let screenFrame = currentScreen?.visibleFrame else { return }
        let margin = Self.screenMargin
        let x = screenFrame.maxX - panel.frame.width - margin
        let y = screenFrame.maxY - panel.frame.height - margin
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }

    /// Native remains the sole authority on the final applied frame — React
    /// only requests, per `03_Native_Host_Blueprint.md` section 3.6.
    /// Requested sizes are floored against `userExpandedSize` so a
    /// content-driven resize (reference paths changing, modality
    /// switching) never shrinks the window below a size the user
    /// deliberately drag-resized it to. The animated `setFrame` is wrapped
    /// in an explicit animation group so `isApplyingProgrammaticResize`
    /// stays true for the animation's full duration, not just this
    /// synchronous call — see `windowDidResize` below.
    private func resizeWindow(to newSize: (width: CGFloat, height: CGFloat)) {
        guard let panel, let viewModel else { return }
        let minSize = viewModel.isTextEntryMode ? Self.textModeSize : Self.voiceModeSize
        panel.minSize = minSize
        panel.contentMinSize = minSize

        let currentFrame = panel.frame
        let screenFrame: NSRect = (panel.screen
            ?? NSScreen.screens.first(where: { $0.visibleFrame.intersects(currentFrame) })
            ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: newSize.width, height: newSize.height)
        let margin = Self.screenMargin

        let availableWidth = max(minSize.width, screenFrame.width - (margin * 2))
        let availableHeight = max(minSize.height, screenFrame.height - (margin * 2))
        let floorWidth = userExpandedSize?.width ?? minSize.width
        let floorHeight = userExpandedSize?.height ?? minSize.height
        let unclampedWidth = max(newSize.width, minSize.width, floorWidth)
        let unclampedHeight = max(newSize.height, minSize.height, floorHeight)
        let clampedWidth = min(unclampedWidth, availableWidth)
        let clampedHeight = min(unclampedHeight, availableHeight)

        var newOriginX = currentFrame.origin.x
        var newOriginY = currentFrame.maxY - clampedHeight
        if currentFrame.origin.x + clampedWidth > screenFrame.maxX - margin {
            newOriginX = currentFrame.maxX - clampedWidth
        }
        newOriginX = max(screenFrame.minX + margin, min(newOriginX, screenFrame.maxX - margin - clampedWidth))
        newOriginY = max(screenFrame.minY + margin, min(newOriginY, screenFrame.maxY - margin - clampedHeight))

        let newFrame = NSRect(
            x: newOriginX,
            y: newOriginY,
            width: clampedWidth,
            height: clampedHeight
        )
        lastCaptureWidgetFrame = newFrame
        isApplyingProgrammaticResize = true
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.2
            panel.animator().setFrame(newFrame, display: true)
        }, completionHandler: { [weak self] in
            Task { @MainActor [weak self] in
                self?.isApplyingProgrammaticResize = false
            }
        })
    }

    // MARK: - Window Command Shortcuts (Cmd+W / Cmd+M)

    /// Identical to `AgentTaskCaptureWindowController`'s local key monitor
    /// (dossier section 1.8), reused verbatim — Cmd+W calls
    /// `viewModel.cancelCapture()` directly (never round-tripping through a
    /// JS intent), Cmd+M miniaturizes.
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
            case "w":
                self.hide()
                return nil
            case "m":
                panel.miniaturize(nil)
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

    // MARK: - NSWindowDelegate

    func windowDidResize(_ notification: Notification) {
        guard let window = notification.object as? NSWindow, window === panel else { return }
        let currentFrame = window.frame

        guard !isApplyingProgrammaticResize else {
            lastCaptureWidgetFrame = currentFrame
            return
        }

        if let lastFrame = lastCaptureWidgetFrame {
            let topRight = NSPoint(x: lastFrame.maxX, y: lastFrame.maxY)
            let anchoredOrigin = NSPoint(
                x: topRight.x - currentFrame.width,
                y: topRight.y - currentFrame.height
            )
            if anchoredOrigin != currentFrame.origin {
                window.setFrameOrigin(anchoredOrigin)
            }
        }
        lastCaptureWidgetFrame = window.frame
        userExpandedSize = window.frame.size
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hide()
        return false
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow, window === panel else { return }
        hideWithoutCanceling()
    }

    private func notifyBackendWidgetClosedIfNeeded(agentTaskId: String?) {
        guard !didNotifyBackendWidgetClosed else { return }
        didNotifyBackendWidgetClosed = true
        Task {
            var message: [String: Any] = [
                "type": "agent_task_widget_closed",
                "is_awaiting_user_input": false,
                "timestamp": Date().timeIntervalSince1970,
            ]
            if let agentTaskId, !agentTaskId.isEmpty {
                message["agent_task_id"] = agentTaskId
            }
            guard let messageData = try? JSONSerialization.data(withJSONObject: message),
                  let messageString = String(data: messageData, encoding: .utf8) else {
                return
            }
            WebSocketService.shared.sendMessage(messageString)
        }
    }
}
