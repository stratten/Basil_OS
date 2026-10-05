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
            contentRect: NSRect(x: 0, y: 0, width: 860, height: 640),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        panel.title = Self.windowTitle
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = false
        panel.worksWhenModal = true
        panel.hasShadow = false
        panel.alphaValue = 1.0
        panel.isOpaque = false
        panel.backgroundColor = NSColor.clear
        panel.isMovableByWindowBackground = true
        panel.delegate = self
        applySidebarMinimumSize(to: panel, sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false)

        let meetingWebView = MeetingAssistantWebView()
        self.meetingWebView = meetingWebView
        meetingWebView.installDragArea(headerHeight: 56)
        meetingWebView.onClose = { [weak self] in self?.close() }
        meetingWebView.onMinimize = { [weak self] in self?.panel?.miniaturize(nil) }
        meetingWebView.onToggleCollapse = { [weak self] collapsed in self?.applyCollapse(collapsed) }

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
            fallbackExpandedSize: NSSize(width: 860, height: 640)
        )

        meetingWebView.loadContent(entryFile: "src/entries/meeting-assistant.html")
        panel.makeKeyAndOrderFront(nil)
        MeetingPresentationCoordinator.shared.standaloneDidBecomeVisible()
    }

    private func applyCollapse(_ collapsed: Bool) {
        collapseController?.setCollapsed(collapsed)
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
        let minimumSize = LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: sidebarCollapsed)
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
            sidebarCollapsed: coordinator.viewModel?.isSidebarCollapsed ?? false
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
        panel = nil
        onClosed?()
    }
}
