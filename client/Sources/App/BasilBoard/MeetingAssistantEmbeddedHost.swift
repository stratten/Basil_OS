import AppKit

/// Owns one embedded Meeting Assistant web view within a BasilBoard web view.
@MainActor
final class MeetingAssistantEmbeddedHost: NSObject {
    let webView: MeetingAssistantWebView
    private let coordinator: MeetingSessionCoordinator
    private var presentationToken: MeetingPresentationToken?
    private let clippingContainer = NSView()
    private var constraints: [NSLayoutConstraint] = []

    /// The native window currently hosting this embedded surface (the main
    /// Board window or a detached "Meetings" Board window, whichever mounted
    /// it). Read by `MeetingSessionCoordinator.showWebMeeting()` via
    /// `MeetingPresentationCoordinator.shared.activeEmbeddedHost` to raise
    /// the right window when the menu-bar entry point is invoked while the
    /// Board is authoritative.
    var hostWindow: NSWindow? { clippingContainer.window }

    func bringHostWindowToFront() {
        guard let hostWindow else { return }
        NSApp.activate(ignoringOtherApps: true)
        if hostWindow.isMiniaturized {
            hostWindow.deminiaturize(nil)
        }
        hostWindow.makeKeyAndOrderFront(nil)
    }

    init(embeddingInto hostView: NSView, topInset: CGFloat, leadingInset: CGFloat, coordinator: MeetingSessionCoordinator) {
        self.webView = MeetingAssistantWebView()
        self.coordinator = coordinator
        super.init()

        MeetingPresentationCoordinator.shared.activeEmbeddedHost = self

        webView.prepareEmbeddedPresentation()

        let token = coordinator.attachWebPresentation(
            sink: { [weak webView] event in webView?.send(event) },
            meterSink: { [weak webView] payload in webView?.publishMeter(payload) }
        )
        presentationToken = token
        webView.onIntent = { [weak self] intent, payload in
            guard let self else { return }
            if intent == .reactReady {
                self.coordinator.webPresentationDidBecomeReady(token)
            } else {
                self.coordinator.handleWebIntent(intent, payload: payload)
            }
        }
        webView.onClose = {
            DevLogger.shared.error(
                "[MeetingAssistantEmbeddedHost] Unexpected closeWindow from embedded surface",
                context: "LiveTranscription"
            )
        }
        webView.onMinimize = {
            DevLogger.shared.error(
                "[MeetingAssistantEmbeddedHost] Unexpected minimizeWindow from embedded surface",
                context: "LiveTranscription"
            )
        }
        webView.onToggleCollapse = { _ in }

        clippingContainer.translatesAutoresizingMaskIntoConstraints = false
        clippingContainer.wantsLayer = true
        clippingContainer.layer?.cornerRadius = 16
        clippingContainer.layer?.maskedCorners = [.layerMaxXMaxYCorner]
        clippingContainer.layer?.masksToBounds = true
        hostView.addSubview(clippingContainer)

        webView.webView.translatesAutoresizingMaskIntoConstraints = false
        webView.webView.wantsLayer = true
        webView.webView.layer?.cornerRadius = 16
        webView.webView.layer?.maskedCorners = [.layerMaxXMaxYCorner]
        webView.webView.layer?.masksToBounds = true
        clippingContainer.addSubview(webView.webView)
        let constraints = [
            clippingContainer.topAnchor.constraint(equalTo: hostView.topAnchor, constant: topInset),
            clippingContainer.leadingAnchor.constraint(equalTo: hostView.leadingAnchor, constant: leadingInset),
            clippingContainer.trailingAnchor.constraint(equalTo: hostView.trailingAnchor, constant: -8),
            clippingContainer.bottomAnchor.constraint(equalTo: hostView.bottomAnchor, constant: -8),
            webView.webView.topAnchor.constraint(equalTo: clippingContainer.topAnchor),
            webView.webView.leadingAnchor.constraint(equalTo: clippingContainer.leadingAnchor),
            webView.webView.trailingAnchor.constraint(equalTo: clippingContainer.trailingAnchor),
            webView.webView.bottomAnchor.constraint(equalTo: clippingContainer.bottomAnchor),
        ]
        NSLayoutConstraint.activate(constraints)
        self.constraints = constraints

        webView.loadContent(entryFile: "src/entries/meeting-assistant.html")
    }

    func tearDown() {
        if MeetingPresentationCoordinator.shared.activeEmbeddedHost === self {
            MeetingPresentationCoordinator.shared.activeEmbeddedHost = nil
        }
        if let presentationToken {
            coordinator.detachPresentation(presentationToken)
        }
        presentationToken = nil
        NSLayoutConstraint.deactivate(constraints)
        constraints.removeAll()
        webView.tearDown()
        webView.webView.removeFromSuperview()
        clippingContainer.removeFromSuperview()
    }
}
