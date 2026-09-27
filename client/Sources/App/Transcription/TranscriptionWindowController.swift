import SwiftUI
import Combine
import AppKit

@MainActor
final class TranscriptionWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    var viewModel: TranscriptionWidgetViewModel?
    private var initializationTask: Task<Void, Never>?
    private var reactWebView: TranscriptionWebView?
    private var bridgeController: TranscriptionBridgeController?
    private var errorPopover: NSPopover?
    private var cancellables = Set<AnyCancellable>()
    // Add a local event monitor for Escape key
    private var localEventMonitor: Any?
    var isVisible: Bool { panel != nil }
    private var savedFullSize: NSSize?
    private var savedMinimizedSize: NSSize?
    /// Fixed footprint of the minimized React chrome. It must match
    /// `.transcription-widget-window-frame--minimized` exactly so the panel
    /// does not show a larger first frame before React paints.
    private let minimizedWindowSize = NSSize(width: 142, height: 73)
    private var collapseController: WindowCollapseController?
    func show(autoStartRecording: Bool = false) {
        guard panel == nil else { return }
        // Cancel any scheduled model unloads
        Task {
            do {
                if WebSocketService.shared.isConnected {
                    try await WebSocketService.shared.cancelModelUnload()
                    print("🚫 Cancelled any scheduled model unloads")
                }
            } catch {
                print("⚠️ Failed to cancel model unload: \(error)")
            }
        }
        let defaultSize = NSSize(width: 400, height: 300)
        let minimizedSize = minimizedWindowSize
        var initialSize = defaultSize
        let settings = APIClient.shared.getCachedTranscriptionSettings()
        let isMinimized = settings.isWidgetMinimized
        var cachedSavedSize: NSSize?
        if let savedSize = settings.widgetSize {
            cachedSavedSize = NSSize(width: CGFloat(savedSize.width), height: CGFloat(savedSize.height))
        }
        if isMinimized {
            // Always create the minimized panel at its final compact size. The
            // persisted widget size is shared across states and can hold a larger
            // (expanded) value; if the panel is born larger than compact, the
            // SwiftUI content lays out against the larger bounds for one frame
            // before it is constrained/collapsed down, which occasionally shows
            // up as the interior elements sliding into place on first appearance.
            initialSize = minimizedSize
        } else if let savedSize = cachedSavedSize {
            initialSize = savedSize
            print("📏 Restoring saved transcription widget size: \(initialSize.width) x \(initialSize.height)")
        }
        if isMinimized {
            savedMinimizedSize = cachedSavedSize ?? initialSize
        } else {
            savedFullSize = cachedSavedSize ?? initialSize
        }
        print("📢 Creating new transcription panel with size: \(initialSize.width) x \(initialSize.height)")
        
        // Use borderless style for both states (as it was working before)
        let styleMask: NSWindow.StyleMask = [.nonactivatingPanel, .borderless, .resizable]
        
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: initialSize.width, height: initialSize.height),
            styleMask: styleMask,
            backing: .buffered,
            defer: false
        )
        panel.title = "Transcription"
        panel.level = .floating
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
            .ignoresCycle
        ]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.worksWhenModal = true
        print("📢 Setting window delegate")
        panel.isMovableByWindowBackground = true
        #if DEBUG
        DevLogger.shared.info("📢 Setting window delegate", context: "TranscriptionWindowController")
        #endif
        panel.delegate = self
        
        // Setup borderless appearance for both states (without window-level corner radius)
        setupBorderlessAppearance(for: panel)
        
        if isMinimized {
            panel.contentMinSize = minimizedSize
            panel.contentMaxSize = minimizedSize
            #if DEBUG
            DevLogger.shared.info("Applied minimized appearance before window is shown", context: "TranscriptionWindowController")
            #endif
        }
        
        let viewModel = TranscriptionWidgetViewModel()
        self.viewModel = viewModel
        viewModel.pendingAutoStartRecording = autoStartRecording
        
        // Set minimized state BEFORE creating the widget to prevent double rendering
        if isMinimized {
            viewModel.isMinimized = true
        }
        
        let webView = TranscriptionWebView()
        self.reactWebView = webView
        panel.contentView = webView.webView
        let bridgeController = TranscriptionBridgeController(
            viewModel: viewModel,
            output: webView,
            showErrorPopover: { [weak self] message in
                self?.showErrorPopover(message)
            }
        )
        self.bridgeController = bridgeController
        AppearanceRefreshCoordinator.shared.register(self)
        webView.onIntent = { [weak bridgeController] intent in bridgeController?.handle(intent: intent) }
        webView.onReady = { [weak bridgeController] in bridgeController?.sendInitialSnapshot() }
        // onResize intentionally left nil: see TranscriptionBridgeController's
        // "requestResize" no-op for why this surface never resizes from React.
        webView.loadContent()
        #if DEBUG
        DevLogger.shared.info("TranscriptionWebView loaded (isModelLoading: \(viewModel.isModelLoading), isProcessingRecording: \(viewModel.isProcessingRecording))", context: "TranscriptionWindowController")
        #endif
        
        // Configure layers for SwiftUI corner radius to work in borderless windows
        if let contentView = panel.contentView {
            contentView.wantsLayer = true
            contentView.layer?.masksToBounds = false  // Allow shadows to show
        }
        
        // Apply proper corner radius after content view is set
        updateCornerRadius()
        
        #if DEBUG
        DevLogger.shared.info("TranscriptionWidget hostingView assigned to panel.contentView", context: "TranscriptionWindowController")
        #endif
        
        var positioned = false
        if let positionData = settings.widgetPosition {
            let x = positionData.x
            let y = positionData.y
            let screenID = positionData.screenID
            let screens = NSScreen.screens
            let targetScreen = screens.first { screen in
                if let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
                    return id.intValue == screenID
                }
                return false
            } ?? NSScreen.main
            if let visibleFrame = targetScreen?.visibleFrame {
                let savedHeight = cachedSavedSize?.height ?? initialSize.height
                let savedTopY = CGFloat(y) + savedHeight
                var desiredOriginY = savedTopY - initialSize.height
                var desiredOriginX = CGFloat(x)
                desiredOriginX = min(max(desiredOriginX, visibleFrame.minX), visibleFrame.maxX - initialSize.width)
                desiredOriginY = min(max(desiredOriginY, visibleFrame.minY), visibleFrame.maxY - initialSize.height)
                panel.setFrameOrigin(NSPoint(x: desiredOriginX, y: desiredOriginY))
                print("📍 Restoring saved transcription widget position: \(desiredOriginX), \(desiredOriginY) on screen \(screenID)")
                positioned = true
            }
        }
        if !positioned, let screenFrame = NSScreen.main?.visibleFrame {
            panel.setFrame(NSRect(
                x: screenFrame.maxX - panel.frame.width - 20,
                y: screenFrame.maxY - panel.frame.height - 20,
                width: panel.frame.width,
                height: panel.frame.height
            ), display: true)
        }
        self.panel = panel
        collapseController = WindowCollapseController(
            window: panel,
            compactSize: minimizedWindowSize,
            fallbackExpandedSize: NSSize(width: 500, height: 300)
        )
        panel.orderFront(nil)
        #if DEBUG
        DevLogger.shared.info("Transcription panel ordered front (visible: \(panel.isVisible))", context: "TranscriptionWindowController")
        #endif
        print("📢 Adding observer for auto-close requests")
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("CloseTranscriptionWidgetRequest"), object: nil)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleCloseRequest),
            name: NSNotification.Name("CloseTranscriptionWidgetRequest"),
            object: nil
        )
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("MinimizedStateChanged"), object: nil)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(updateWindowForMinimizedState),
            name: NSNotification.Name("MinimizedStateChanged"),
            object: nil
        )
        NotificationCenter.default.removeObserver(self, name: NSNotification.Name("RecordingStateChanged"), object: nil)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleRecordingStateChange),
            name: NSNotification.Name("RecordingStateChanged"),
            object: nil
        )
        #if DEBUG
        DevLogger.shared.info("Added observers for widget state changes", context: "TranscriptionWindowController")
        #endif
        initializationTask = Task { [weak self, weak viewModel] in
            guard let viewModel else { return }
            await viewModel.initialize(autoStartRecording: autoStartRecording)
            self?.initializationTask = nil
        }
    }
    @objc private func handleRecordingStateChange(_ notification: Notification) {
        guard let isRecording = notification.userInfo?["isRecording"] as? Bool else { return }
        #if DEBUG
        DevLogger.shared.info("Recording state changed to: \(isRecording), notifying HotkeyService", context: "TranscriptionWindowController")
        #endif
        if let monitor = localEventMonitor {
            NSEvent.removeMonitor(monitor)
            localEventMonitor = nil
            #if DEBUG
            DevLogger.shared.info("Removed local Escape key monitor (using global monitor instead)", context: "TranscriptionWindowController")
            #endif
        }
    }
    @objc private func handleCloseRequest(_ notification: Notification) {
        #if DEBUG
        let reason = notification.userInfo?["reason"] as? String ?? "auto-close preference"
        DevLogger.shared.info("Received auto-close request (\(reason)), hiding transcription widget", context: "auto_close")
        DevLogger.shared.info("Auto-close notification - Current window state: isVisible=\(isVisible), isRecording=\(isRecording)", context: "auto_close")
        #endif
        hide()
        #if DEBUG
        DevLogger.shared.info("Auto-close - Widget hide operation completed", context: "auto_close")
        #endif
    }
    func hide() {
        guard panel != nil else { return }
        if viewModel?.isRecording == true {
            viewModel?.stopRecording()
        }
        if let monitor = localEventMonitor {
            NSEvent.removeMonitor(monitor)
            localEventMonitor = nil
            #if DEBUG
            DevLogger.shared.info("Local Escape key monitor removed on hide", context: "TranscriptionWidget")
            #endif
        }
        Task {
            do {
                let settings = APIClient.shared.getCachedTranscriptionSettings()
                let delaySeconds = settings.modelUnloadDelay
                print("📋 Transcription widget closing, unload delay set to: \(delaySeconds) seconds")
                if delaySeconds >= 0 {
                    if WebSocketService.shared.isConnected {
                        print("📢 Attempting to schedule model unload via WebSocket")
                        try await WebSocketService.shared.scheduleModelUnload(delaySeconds: delaySeconds)
                        print("⏲️ Model unload scheduled successfully")
                    } else {
                        print("⚠️ WebSocket not connected, cannot schedule model unload")
                    }
                } else {
                    print("⚠️ Invalid unload delay: \(delaySeconds), skipping unload")
                }
            } catch {
                print("❌ Failed to schedule model unload: \(error)")
            }
        }
        print("📢 Cleaning up view model and window")
        viewModel?.cleanup()
        cleanupWindow()
    }
    private func showErrorPopover(_ message: String) {
        guard let panel, let webView = reactWebView?.webView else { return }

        errorPopover?.performClose(nil)
        let popover = NSPopover()
        popover.behavior = .transient
        popover.contentSize = NSSize(width: 240, height: 96)
        popover.contentViewController = NSHostingController(
            rootView: VStack(alignment: .leading, spacing: 6) {
                Text("Transcription failed")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(AestheticSystem.Colors.errorBase)
                Text(message)
                    .font(.system(size: 12))
                    .foregroundColor(AestheticSystem.Colors.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(12)
            .frame(width: 240, alignment: .leading)
        )
        errorPopover = popover

        let bounds = webView.bounds
        let anchor = NSRect(
            x: max(0, bounds.maxX - 20),
            y: max(0, bounds.maxY - 20),
            width: min(20, bounds.width),
            height: min(20, bounds.height)
        )
        popover.show(relativeTo: anchor, of: webView, preferredEdge: .maxY)
        panel.makeKey()
    }

    func refreshAppearance() {
        bridgeController?.sendThemeChanged()
    }

    nonisolated private func cleanupWindow() {
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            AppearanceRefreshCoordinator.shared.unregister(self)
            self.viewModel?.cleanup()
            if let monitor = self.localEventMonitor {
                NSEvent.removeMonitor(monitor)
                self.localEventMonitor = nil
                #if DEBUG
                DevLogger.shared.info("Local Escape key monitor removed during cleanup", context: "TranscriptionWidget")
                #endif
            }
            if let panel = self.panel {
                panel.close()
            }
            self.panel = nil
            self.viewModel = nil
            self.errorPopover?.performClose(nil)
            self.errorPopover = nil
            self.reactWebView?.tearDown()
            self.reactWebView = nil
            self.bridgeController = nil
            self.initializationTask?.cancel()
            self.initializationTask = nil
        }
    }
    @MainActor
    var isRecording: Bool {
        viewModel?.isRecording ?? false
    }
    var isStartingRecording: Bool {
        viewModel?.isStartingRecording ?? false
    }
    var isProcessingRecording: Bool {
        viewModel?.isProcessingRecording ?? false
    }
    var hotkeyRecordingState: TranscriptionHotkeyGestureState.ControllerState {
        guard let viewModel else { return .idle }
        if viewModel.isStartingRecording { return .starting }
        if viewModel.isRecording { return .recording }
        if viewModel.isProcessingRecording { return .processing }
        if viewModel.recordingLifecycle == .failed { return .failed }
        return .idle
    }
    var recordingStatePublisher: AnyPublisher<Bool, Never> {
        let publisher = viewModel?.$isRecording.eraseToAnyPublisher() ?? Just(false).eraseToAnyPublisher()
        #if DEBUG
        return publisher
        #else
        return publisher
        #endif
    }
    func startRecording() async {
        if panel == nil {
            print("📱 Creating new transcription window")
            show(autoStartRecording: true)
            await initializationTask?.value
            panel?.orderFront(nil)
            return
        }
        panel?.orderFront(nil)
        if viewModel?.isStartingRecording == true {
            viewModel?.cancelRecordingStartup()
            return
        }
        if let vm = viewModel {
            if vm.isConnected {
                print("🎙️ Starting recording with existing window")
                await vm.startRecording()
            } else {
                print("⚠️ Cannot start recording - reinitializing view model")
                await vm.initialize(autoStartRecording: true)
            }
        }
    }
    func stopRecording() {
        viewModel?.stopRecording()
    }
    @MainActor
    func cancelRecording() async {
        guard let vm = viewModel, vm.isRecording || vm.isStartingRecording else {
            #if DEBUG
            DevLogger.shared.info("Ignoring cancelRecording call - no recording in progress", context: "TranscriptionWindowController")
            #endif
            return
        }
        #if DEBUG
        DevLogger.shared.info("TranscriptionWindowController: Canceling recording", context: "TranscriptionWindowController")
        #endif
        await vm.cancelRecording()
    }
    deinit {
        cleanupWindow()
        cancellables.removeAll()
        NotificationCenter.default.removeObserver(
            self,
            name: NSNotification.Name("CloseTranscriptionWidgetRequest"),
            object: nil
        )
        NotificationCenter.default.removeObserver(
            self,
            name: NSNotification.Name("MinimizedStateChanged"),
            object: nil
        )
        NotificationCenter.default.removeObserver(
            self,
            name: NSNotification.Name("RecordingStateChanged"),
            object: nil
        )
        if let monitor = localEventMonitor {
            NSEvent.removeMonitor(monitor)
            localEventMonitor = nil
            #if DEBUG
            DevLogger.shared.info("Local Escape key monitor removed", context: "TranscriptionWidget")
            #endif
        }
    }
    // Notification-driven entry point (user tapped minimize/expand). The reframe
    // animates so the transition reads as intentional motion, matching the other
    // WindowChromeCollapse-backed windows.
    @objc func updateWindowForMinimizedState() {
        applyMinimizedState(animated: true)
    }

    // Applies the current minimized/expanded state to the panel. `animated`
    // controls only the collapse reframe: the initial-show application passes
    // `false` so the widget simply appears already-compact instead of gliding
    // to size right as the model finishes loading (the "shake" on first open);
    // user-initiated toggles pass `true`.
    private func applyMinimizedState(animated: Bool) {
        guard let panel = panel, let viewModel = viewModel else { return }
        #if DEBUG
        DevLogger.shared.info("Updating window for minimized state: \(viewModel.isMinimized) (animated: \(animated))", context: "TranscriptionWindowController")
        #endif
        
        let minimizedSize = minimizedWindowSize
        
        if viewModel.isMinimized {
            // Save current size before minimizing
            if panel.frame.size.height > minimizedSize.height {
                let currentSize = panel.frame.size
                #if DEBUG
                DevLogger.shared.info("Saving current window size before minimizing: \(currentSize.width) x \(currentSize.height)", context: "TranscriptionWindowController")
                #endif
                savedFullSize = currentSize
            }
            
            collapseController?.setCollapsed(true, preferredCompactSize: minimizedSize, animated: animated)
            
            #if DEBUG
            DevLogger.shared.info("Window resized to minimized size: \(panel.frame.size.width) x \(panel.frame.size.height)", context: "TranscriptionWindowController")
            #endif
        } else {
            // Restore saved size or use default
            let targetSize = savedFullSize ?? NSSize(width: 500, height: 300)
            if collapseController?.isCollapsed != true {
                panel.minSize = NSSize(width: 300, height: 200)
                panel.contentMinSize = NSSize(width: 300, height: 200)
                panel.contentMaxSize = NSSize(
                    width: CGFloat.greatestFiniteMagnitude,
                    height: CGFloat.greatestFiniteMagnitude
                )
            }
            collapseController?.setCollapsed(false, fallbackExpandedSize: targetSize)
            
            #if DEBUG
            DevLogger.shared.info("Window restored to full size: \(panel.frame.size.width) x \(panel.frame.size.height)", context: "TranscriptionWindowController")
            #endif
        }
        
        // Update corner radius to match the new state
        updateCornerRadius()
    }
    private func setupBorderlessAppearance(for panel: NSPanel) {
        #if DEBUG
        DevLogger.shared.info("Setting up borderless appearance with proper corner radius", context: "TranscriptionWindowController")
        #endif
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isOpaque = false
        panel.isMovableByWindowBackground = true
    }
    
    private func updateCornerRadius() {
        guard let panel = panel, let contentView = panel.contentView else { return }
        
        contentView.wantsLayer = true
        contentView.layer?.masksToBounds = true
        
        // Use different corner radius based on minimized state
        let cornerRadius: CGFloat = viewModel?.isMinimized == true ? 12 : 16
        contentView.layer?.cornerRadius = cornerRadius
        
        #if DEBUG
        DevLogger.shared.info("Updated window corner radius to \(cornerRadius) (minimized: \(viewModel?.isMinimized == true))", context: "TranscriptionWindowController")
        #endif
    }
    
}
// MARK: - NSWindowDelegate
extension TranscriptionWindowController {
    func windowDidResize(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        let size = window.frame.size
        print("Transcription widget resized to: \(size.width) x \(size.height)")
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(saveWindowSize), object: nil)
        perform(#selector(saveWindowSize), with: nil, afterDelay: 0.5)
    }
    func windowDidMove(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        let position = window.frame.origin
        print("Transcription widget moved to: \(position.x), \(position.y)")
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(saveWindowPosition), object: nil)
        perform(#selector(saveWindowPosition), with: nil, afterDelay: 0.5)
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        print("📢 windowShouldClose called for transcription widget")
        hide()
        return false
    }
    func windowWillClose(_ notification: Notification) {
        print("📢 windowWillClose called for transcription widget")
        guard let window = notification.object as? NSWindow else { return }
        if window == panel {
            print("📢 Handling window close event via windowWillClose")
            hide()
        }
    }
    @objc private func saveWindowSize() {
        guard let size = panel?.frame.size else { return }
        if viewModel?.isMinimized == true {
            savedMinimizedSize = size
        } else {
            savedFullSize = size
        }
        print("Saving transcription widget size: \(size.width) x \(size.height)")
        Task {
            do {
                do {
                    let data = try await APIClient.shared.get("/settings/transcription")
                    if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
                        #if DEBUG
                        DevLogger.shared.info("Refreshed settings before saving widget size", context: "widget_persistence")
                        #endif
                        APIClient.shared.cacheTranscriptionSettings(response.settings)
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to refresh settings before saving widget size: \(error)", context: "widget_persistence")
                    #endif
                }
                try await APIClient.shared.updateTranscriptionWidgetSize(size)
            } catch {
                print("❌ Failed to save widget size: \(error)")
            }
        }
    }
    @objc private func saveWindowPosition() {
        guard let window = panel,
              let screen = window.screen else { return }
        let position = window.frame.origin
        var screenID = 0
        if let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
            screenID = id.intValue
        }
        print("Saving transcription widget position: \(position.x), \(position.y) on screen \(screenID)")
        Task {
            do {
                do {
                    let data = try await APIClient.shared.get("/settings/transcription")
                    if let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
                        #if DEBUG
                        DevLogger.shared.info("Refreshed settings before saving widget position", context: "widget_persistence")
                        #endif
                        APIClient.shared.cacheTranscriptionSettings(response.settings)
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to refresh settings before saving widget position: \(error)", context: "widget_persistence")
                    #endif
                }
                try await APIClient.shared.updateTranscriptionWidgetPosition(position, screenID: screenID)
            } catch {
                print("❌ Failed to save widget position: \(error)")
            }
        }
    }
}
// MARK: - Safe Array Extension
extension Array {
    subscript(safe index: Index) -> Element? {
        return indices.contains(index) ? self[index] : nil
    }
} 