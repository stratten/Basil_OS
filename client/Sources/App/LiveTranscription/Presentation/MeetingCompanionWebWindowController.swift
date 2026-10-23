import AppKit
import Foundation

/// Detached WebKit window for the live Companion. It is one more presentation of the shared Notetaker session (same pattern as `MeetingAnalysisWebWindowController`): it receives the same UI snapshots and forwards intents through the coordinator's single validated handler.
@MainActor
final class MeetingCompanionWebWindowController: NSObject, NSWindowDelegate {
    private let coordinator: MeetingSessionCoordinator
    private var window: NSWindow?
    private var meetingWebView: MeetingAssistantWebView?
    private var presentationToken: MeetingPresentationToken?
    private var collapseController: WindowCollapseController?

    var onClosed: (() -> Void)?
    /// Fired when the window's page completes the ready handshake, so the Companion is on screen here before the Notetaker folds its own copy away.
    var onReady: (() -> Void)?

    init(coordinator: MeetingSessionCoordinator) {
        self.coordinator = coordinator
        super.init()
    }

    func show() {
        if let window {
            if window.isMiniaturized {
                window.deminiaturize(nil)
            }
            window.makeKeyAndOrderFront(nil)
            window.orderFrontRegardless()
            return
        }

        let window = ClosableBorderlessPanel(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 680),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.configureFloatingWidget(title: "Notetaker Companion", transparency: .clearWithoutShadow)
        window.minSize = NSSize(width: 340, height: 420)
        window.delegate = self

        let meetingWebView = MeetingAssistantWebView()
        self.meetingWebView = meetingWebView
        meetingWebView.installDragArea()
        meetingWebView.onClose = { [weak self] in self?.window?.close() }
        meetingWebView.onMinimize = { [weak self] in self?.window?.miniaturize(nil) }
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
        meetingWebView.onIntent = { [weak self] intent, payload in
            guard let self else { return }
            if intent == .reactReady {
                self.coordinator.webPresentationDidBecomeReady(token)
                self.onReady?()
            } else {
                self.coordinator.handleWebIntent(intent, payload: payload)
            }
        }

        window.contentView = meetingWebView.webView
        WebKitWindowChromeAppearance.apply(to: window)
        window.center()
        self.window = window
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 280, height: 64),
            fallbackExpandedSize: NSSize(width: 420, height: 680)
        )

        meetingWebView.loadContent(entryFile: "src/entries/meeting-companion.html")
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }

    private func applyCollapse(_ collapsed: Bool) {
        meetingWebView?.installDragArea(trailingInteractiveWidth: collapsed ? 0 : 76)
        collapseController?.setCollapsed(collapsed)
    }

    func windowWillClose(_ notification: Notification) {
        if let presentationToken {
            coordinator.detachPresentation(presentationToken)
        }
        presentationToken = nil
        meetingWebView?.tearDown()
        meetingWebView = nil
        collapseController = nil
        window = nil
        onClosed?()
    }
}
