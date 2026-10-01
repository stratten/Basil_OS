import AppKit
import SwiftUI
import Combine

/// Window controller for the floating model download mini widget.
/// Renders the arbitrary model set supplied by `GlobalModelDownloadMonitor`,
/// regardless of which application surface started the downloads.
@MainActor
final class ModelDownloadWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    private var webViewHost: ModelDownloadMiniPanelWebView?
    private var cancellables = Set<AnyCancellable>()
    private var rendererReadyTimeoutTask: Task<Void, Never>?
    private lazy var appIconDataUrl = ModelDownloadMiniPanelTheme.appIconDataUrl()
    private var latestEntries: [ModelDownloadActivityEntry] = []
    private var hasLoadedContent = false
    
    var isVisible: Bool { panel != nil && (panel?.isVisible ?? false) }
    
    // MARK: - Public API
    
    /// Create and show the panel shell. The monitor supplies its content through
    /// `apply(entries:)` immediately after showing it.
    func show() {
        guard panel == nil else {
            panel?.orderFront(nil)
            return
        }
        
        let widgetSize = NSSize(width: 280, height: 220)
        
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: widgetSize.width, height: widgetSize.height),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        
        panel.title = "Model Downloads"
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
        panel.hasShadow = false // Widget has its own shadow
        panel.alphaValue = 1.0
        panel.isOpaque = false
        panel.backgroundColor = NSColor.clear
        panel.isMovableByWindowBackground = true
        
        panel.delegate = self
        
        let webViewHost = ModelDownloadMiniPanelWebView()
        self.webViewHost = webViewHost
        webViewHost.isKnownModelId = { [weak self] modelId in
            self?.latestEntries.contains { $0.modelId == modelId } == true
        }
        webViewHost.onRendererReady = { [weak self] in
            self?.rendererReadyTimeoutTask?.cancel()
            self?.rendererReadyTimeoutTask = nil
        }
        webViewHost.onDismiss = { [weak self] in
            self?.dismiss()
        }
        webViewHost.onRetryModel = { modelId in
            Self.retryDownload(modelId: modelId)
        }
        webViewHost.onCancelModel = { modelId in
            Self.cancelDownload(modelId: modelId)
        }
        webViewHost.onResizeRequested = { [weak self] size in
            self?.resizePanel(to: size)
        }
        webViewHost.onNavigationFailed = {
            #if DEBUG
            DevLogger.shared.error("ModelDownloadMiniPanelWebView navigation failed", context: "ModelDownload")
            #endif
        }
        panel.contentView = webViewHost.webView
        
        setupBorderlessAppearance(for: panel)
        positionBottomRight(panel)
        
        self.panel = panel
        panel.orderFront(nil)
        hasLoadedContent = false
        AppearanceRefreshCoordinator.shared.register(self)

        rendererReadyTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard !Task.isCancelled, self?.webViewHost != nil else { return }
            #if DEBUG
            DevLogger.shared.error("ModelDownloadMiniPanelWebView renderer did not report ready within timeout", context: "ModelDownload")
            #endif
        }

        #if DEBUG
        DevLogger.shared.info("ModelDownloadWindowController shown", context: "ModelDownload")
        #endif
    }

    func apply(entries: [ModelDownloadActivityEntry]) {
        latestEntries = entries
        let snapshot = snapshot(from: entries)
        guard let webViewHost else { return }
        if hasLoadedContent {
            webViewHost.sendSnapshot(snapshot)
        } else {
            webViewHost.loadContent(snapshot: snapshot)
            hasLoadedContent = true
        }
    }
    
    /// Dismiss and release the widget
    func dismiss() {
        guard let panel = panel else { return }
        
        // Fade out
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.3
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            Task { @MainActor in
                panel.orderOut(nil)
                self?.cleanup()
            }
        })
        
        #if DEBUG
        DevLogger.shared.info("ModelDownloadWindowController dismissed", context: "ModelDownload")
        #endif
    }
    
    // MARK: - Private

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    private func cleanup() {
        rendererReadyTimeoutTask?.cancel()
        rendererReadyTimeoutTask = nil
        cancellables.removeAll()
        AppearanceRefreshCoordinator.shared.unregister(self)
        webViewHost?.tearDown()
        webViewHost = nil
        panel?.delegate = nil
        panel = nil
        latestEntries = []
        hasLoadedContent = false
    }

    /// Position the panel in the bottom-right corner of the active screen.
    private func positionBottomRight(_ panel: NSPanel) {
        let mouseLocation = NSEvent.mouseLocation
        let targetScreen = NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) } ?? NSScreen.main
        
        guard let screen = targetScreen else {
            panel.center()
            return
        }
        
        let visibleFrame = screen.visibleFrame
        let panelSize = panel.frame.size
        let padding: CGFloat = 16
        
        let originX = visibleFrame.maxX - panelSize.width - padding
        let originY = visibleFrame.origin.y + padding
        
        panel.setFrameOrigin(NSPoint(x: originX, y: originY))
    }

    private func snapshot(from entries: [ModelDownloadActivityEntry]) -> ModelDownloadPanelSnapshot {
        let modelCount = max(entries.count, 1)
        let readyStatuses: Set<String> = ["completed", "skipped_installed"]
        let readyCount = entries.filter { readyStatuses.contains($0.status) }.count
        let isComplete = !entries.isEmpty && readyCount == entries.count
        let hasFailedEntry = entries.contains { $0.status == "failed" || $0.status == "user_canceled" }
        let rows = entries.map { entry in
            return ModelDownloadPanelSnapshot.Row(
                modelId: entry.modelId,
                status: entry.status,
                progress: entry.progress * 100,
                totalDownloaded: entry.totalDownloaded,
                totalSize: entry.totalSize,
                isRetrying: false
            )
        }
        return ModelDownloadPanelSnapshot(
            phaseMessage: isComplete ? "Model setup complete" : hasFailedEntry ? "Download needs attention" : "Downloading models…",
            isComplete: isComplete,
            quantizedPercentage: Int(Double(readyCount) / Double(modelCount) * 100),
            appIconDataUrl: appIconDataUrl,
            models: rows
        )
    }

    private func resizePanel(to contentSize: CGSize) {
        guard let panel else { return }
        let chromeInset = WebKitWindowChromeAppearance.frameInset
        let size = NSSize(
            width: contentSize.width + chromeInset * 2,
            height: contentSize.height + chromeInset * 2
        )
        let currentFrame = panel.frame
        let frame = NSRect(
            x: currentFrame.maxX - size.width,
            y: currentFrame.minY,
            width: size.width,
            height: size.height
        )
        panel.setFrame(frame, display: panel.isVisible, animate: panel.isVisible)
    }

    private static func cancelDownload(modelId: String) {
        guard let (modelType, variant) = parseModelId(modelId) else { return }
        Task {
            _ = try? await APIClient.shared.post("/models/cancel", [
                "model_type": modelType,
                "variant": variant
            ])
        }
    }

    private static func retryDownload(modelId: String) {
        guard let (modelType, variant) = parseModelId(modelId) else { return }
        Task {
            _ = try? await APIClient.shared.post("/models/download", [
                "request": ["model_type": modelType, "variant": variant]
            ])
        }
    }

    private static func parseModelId(_ modelId: String) -> (String, String)? {
        guard let firstHyphen = modelId.firstIndex(of: "-") else { return nil }
        return (
            String(modelId[..<firstHyphen]),
            String(modelId[modelId.index(after: firstHyphen)...])
        )
    }
    
    private func setupBorderlessAppearance(for panel: NSPanel) {
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isOpaque = false
        
        if let contentView = panel.contentView {
            contentView.wantsLayer = true
            contentView.layer?.cornerRadius = 12
            contentView.layer?.masksToBounds = true
        }
    }
    
    // MARK: - NSWindowDelegate
    
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        dismiss()
        return false
    }
    
    deinit {
        cancellables.removeAll()
        MainActor.assumeIsolated {
            AppearanceRefreshCoordinator.shared.unregister(self)
        }
        #if DEBUG
        DevLogger.shared.info("ModelDownloadWindowController deinit", context: "ModelDownload")
        #endif
    }
}
