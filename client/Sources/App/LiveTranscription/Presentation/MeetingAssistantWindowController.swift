import AppKit
import Combine
import Foundation

/// Borderless-panel host for the default WebKit Meeting Assistant window.
/// Owns only WebKit chrome and panel sizing; every behavior (recording,
/// selection, analysis, proposals) is delegated to `MeetingSessionCoordinator`
/// via the typed bridge. Preserves the established panel's min size, floating
/// behavior, drag area, close, minimize, collapse, and Cmd+W handling by
/// reusing `LiveTranscriptionLayoutPolicy`, `ClosableBorderlessPanel`, and
/// `WindowChromeCollapse`.
@MainActor
final class MeetingAssistantWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    static let windowTitle = "Notetaker"

    private let coordinator: MeetingSessionCoordinator
    private var panel: NSPanel?
    private var meetingWebView: MeetingAssistantWebView?
    private var presentationToken: MeetingPresentationToken?
    private var collapseController: WindowCollapseController?
    private var sidebarStateCancellable: AnyCancellable?
    /// Width the window has actually grown by for the Companion; less than the width the web view asked for only when the screen ran out of room.
    private var companionGrowth: CGFloat = 0

    /// Matches the web sidebar transition (`collapsible-sidebar.css`: 400ms, cubic-bezier(0.2, 0.8, 0.2, 1)) so the window edge and the column move together.
    private static let companionResizeDuration: TimeInterval = 0.4

    var onClosed: (() -> Void)?
    var isVisible: Bool { panel != nil }

    init(coordinator: MeetingSessionCoordinator) {
        self.coordinator = coordinator
        super.init()
    }

    func show() {
        if let existingPanel = panel {
            if existingPanel.isMiniaturized {
                existingPanel.deminiaturize(nil)
            }
            existingPanel.makeKeyAndOrderFront(nil)
            return
        }

        let panel = ClosableBorderlessPanel(
            contentRect: NSRect(x: 0, y: 0, width: 920, height: 640),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        panel.configureFloatingWidget(title: Self.windowTitle, transparency: .clearWithoutShadow)
        panel.isFloatingPanel = true
        panel.becomesKeyOnlyIfNeeded = false
        panel.worksWhenModal = true
        panel.delegate = self
        applySidebarMinimumSize(to: panel, sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false)

        let meetingWebView = MeetingAssistantWebView()
        self.meetingWebView = meetingWebView
        meetingWebView.installDragArea(headerHeight: 56)
        meetingWebView.onClose = { [weak self] in self?.close() }
        meetingWebView.onMinimize = { [weak self] in self?.panel?.miniaturize(nil) }
        meetingWebView.onToggleCollapse = { [weak self] collapsed in self?.applyCollapse(collapsed) }
        meetingWebView.onCompanionPaneExtent = { [weak self] extent in self?.applyCompanionPaneExtent(extent) }

        let token = coordinator.attachWebPresentation(
            sink: { [weak meetingWebView] event in
                meetingWebView?.send(event)
            },
            meterSink: { [weak meetingWebView] payload in
                meetingWebView?.publishMeter(payload)
            }
        )
        presentationToken = token
        AppearanceRefreshCoordinator.shared.register(self)
        sidebarStateCancellable = coordinator.viewModel?.$isSidebarCollapsed
            .removeDuplicates()
            .sink { [weak self] collapsed in
                self?.applySidebarMinimumSize(sidebarCollapsed: collapsed)
            }
        meetingWebView.onIntent = { [weak self] intent, payload in
            guard let self else { return }
            if intent == .reactReady {
                self.coordinator.webPresentationDidBecomeReady(token)
            } else {
                self.coordinator.handleWebIntent(intent, payload: payload)
            }
        }

        panel.contentView = meetingWebView.webView
        WebKitWindowChromeAppearance.apply(to: panel)
        panel.center()
        self.panel = panel
        collapseController = WindowCollapseController(
            window: panel,
            compactSize: LiveTranscriptionLayoutPolicy.compactSize,
            fallbackExpandedSize: NSSize(width: 920, height: 640)
        )

        meetingWebView.loadContent(entryFile: "src/entries/meeting-assistant.html")
        panel.makeKeyAndOrderFront(nil)
        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
    }

    private func applyCollapse(_ collapsed: Bool) {
        collapseController?.setCollapsed(collapsed)
    }

    /// Grows (or shrinks) the window's right edge by the Companion column's width, so the main column never gets narrower. While the window is compact the request is ignored, and the next report reconciles against the real growth.
    private func applyCompanionPaneExtent(_ extent: CGFloat) {
        guard collapseController?.isCollapsed != true, let panel else { return }
        let previousGrowth = companionGrowth
        let baseMinimumWidth = LiveTranscriptionLayoutPolicy.panelMinimumSize(
            sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false
        ).width
        let visibleFrame = (panel.screen ?? NSScreen.main)?.visibleFrame ?? panel.frame
        let resized = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: panel.frame,
            delta: extent - previousGrowth,
            visibleFrame: visibleFrame,
            minimumWidth: baseMinimumWidth
        )
        let newGrowth = max(previousGrowth + resized.achievedDelta, 0)
        guard resized.frame != panel.frame else {
            companionGrowth = newGrowth
            applySidebarMinimumSize(sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false)
            return
        }
        // Lower the floor first when shrinking and raise it only once the window is wide enough when growing, so the floor never exceeds the frame mid-animation.
        companionGrowth = min(previousGrowth, newGrowth)
        applySidebarMinimumSize(sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false)
        NSAnimationContext.runAnimationGroup { context in
            context.duration = Self.companionResizeDuration
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 0.8, 0.2, 1)
            panel.animator().setFrame(resized.frame, display: true)
        } completionHandler: { [weak self] in
            guard let self else { return }
            self.companionGrowth = newGrowth
            self.applySidebarMinimumSize(sidebarCollapsed: self.coordinator.viewModel?.isSidebarCollapsed ?? false)
        }
    }

    private func close() {
        guard let panel else { return }
        panel.close()
    }

    private func applySidebarMinimumSize(sidebarCollapsed: Bool) {
        guard collapseController?.isCollapsed != true, let panel else { return }
        applySidebarMinimumSize(to: panel, sidebarCollapsed: sidebarCollapsed)
    }

    private func applySidebarMinimumSize(
        to panel: NSPanel,
        sidebarCollapsed: Bool
    ) {
        let minimumSize = LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: sidebarCollapsed, companionExtent: companionGrowth)
        panel.minSize = minimumSize
        panel.contentMinSize = minimumSize
        guard !sidebarCollapsed, panel.frame.width < minimumSize.width else { return }
        var frame = panel.frame
        frame.size.width = minimumSize.width
        panel.setFrame(frame, display: true)
    }

    func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
        guard collapseController?.isCollapsed != true else { return frameSize }
        return LiveTranscriptionLayoutPolicy.constrainedExpandedSize(
            frameSize,
            sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false,
            companionExtent: companionGrowth
        )
    }

    func windowWillClose(_ notification: Notification) {
        teardown()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { true }

    func refreshAppearance() {
        guard let token = presentationToken else { return }
        coordinator.bridgePublisher?.sendSnapshot(to: token)
    }

    private func teardown() {
        MeetingPresentationCoordinator.shared.standaloneDidDismiss()
        if let token = presentationToken {
            coordinator.detachPresentation(token)
        }
        presentationToken = nil
        AppearanceRefreshCoordinator.shared.unregister(self)
        meetingWebView?.tearDown()
        meetingWebView = nil
        sidebarStateCancellable = nil
        collapseController = nil
        companionGrowth = 0
        panel = nil
        onClosed?()
    }
}
