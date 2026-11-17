import AppKit

/// Opens tasks launched from the setup flow in a pane to the right of the setup flow, inside the same window, instead of in a separate floating task window.
///
/// The setup window's content view becomes `containerView`, which holds the setup flow on the left and, while a task is showing, a `SetupTaskPaneView` on the right. The task view is the same embedded `AgentTaskResultWebView` host the Board uses, with a layout that fills the pane. It does not claim the presentation coordinator's embedded-host handle (see `AgentTaskResultEmbeddedHost.Layout.isBoardPresenter`), so a Board and a setup pane never take each other over.
@MainActor
final class SetupTaskPaneController {
    /// The setup window's content view. It holds the setup flow and, while open, the task pane.
    let containerView = NSView()

    private let setupContentView: NSView
    private weak var window: NSWindow?
    private let baseContentMinSize: NSSize
    private let minimumSetupWidth: CGFloat
    private let setupFillsContainer: NSLayoutConstraint

    private var paneView: SetupTaskPaneView?
    private var paneConstraints: [NSLayoutConstraint] = []
    private var host: AgentTaskResultEmbeddedHost?
    private var paneWidth: CGFloat = 0
    private var isWindowCollapsed = false

    /// Whether a task is currently showing in the pane (including while the window is collapsed and the pane is tucked away).
    var isShowing: Bool { paneView != nil }

    /// `setupContentView` is the setup flow's hosting view. `minimumSetupWidth` is the narrowest the setup flow may become, which is the window's own minimum width before any pane opens.
    init(window: NSWindow, setupContentView: NSView, minimumSetupWidth: CGFloat) {
        self.window = window
        self.setupContentView = setupContentView
        self.minimumSetupWidth = minimumSetupWidth
        self.baseContentMinSize = window.contentMinSize

        setupContentView.translatesAutoresizingMaskIntoConstraints = false
        containerView.addSubview(setupContentView)
        setupFillsContainer = setupContentView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor)
        NSLayoutConstraint.activate([
            setupContentView.topAnchor.constraint(equalTo: containerView.topAnchor),
            setupContentView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            setupContentView.bottomAnchor.constraint(equalTo: containerView.bottomAnchor),
            setupFillsContainer,
        ])
    }

    /// Shows the task in the pane, opening the pane first when it is closed. Returns false when the pane cannot be used (the window is collapsed or the screen is too narrow), so the caller falls back to the floating task window.
    @discardableResult
    func show(agentTaskId: String, referencePaths: [URL] = []) -> Bool {
        guard let window, !isWindowCollapsed else { return false }

        if let host {
            host.dispatchOrQueueWebCommand(.register(agentTaskId: agentTaskId, referencePaths: referencePaths))
            return true
        }

        guard let screen = window.screen ?? NSScreen.main,
              let plan = SetupTaskPaneFrames.openingPlan(
                  currentFrame: window.frame,
                  minimumSetupWidth: minimumSetupWidth,
                  visibleFrame: screen.visibleFrame
              ) else { return false }

        let pane = SetupTaskPaneView(frame: .zero)
        pane.onCloseRequested = { [weak self] in self?.hide() }
        pane.translatesAutoresizingMaskIntoConstraints = false
        containerView.addSubview(pane)
        paneView = pane
        paneWidth = plan.paneWidth

        let inset = WebKitWindowChromeAppearance.frameInset
        paneConstraints = [
            pane.topAnchor.constraint(equalTo: containerView.topAnchor, constant: inset),
            pane.bottomAnchor.constraint(equalTo: containerView.bottomAnchor, constant: -inset),
            pane.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -inset),
            pane.widthAnchor.constraint(equalToConstant: plan.paneWidth),
            setupContentView.trailingAnchor.constraint(equalTo: pane.leadingAnchor),
        ]
        setupFillsContainer.isActive = false
        NSLayoutConstraint.activate(paneConstraints)

        // Keep the user from dragging the setup flow narrower than it can lay out while the pane is open.
        window.contentMinSize = NSSize(
            width: baseContentMinSize.width + plan.paneWidth,
            height: baseContentMinSize.height
        )
        window.setFrame(plan.windowFrame, display: true, animate: true)

        let newHost = AgentTaskResultEmbeddedHost(
            embeddingInto: pane.bodyView,
            layout: .setupPane,
            originatingWindow: window
        )
        host = newHost
        newHost.dispatchOrQueueWebCommand(.register(agentTaskId: agentTaskId, referencePaths: referencePaths))
        return true
    }

    /// Closes the pane and gives its width back. The task keeps running; it stays in the Agents list.
    func hide() {
        guard paneView != nil else { return }
        let wasCollapsed = isWindowCollapsed
        removePane()
        guard let window else { return }
        window.contentMinSize = baseContentMinSize
        if !wasCollapsed {
            window.setFrame(
                SetupTaskPaneFrames.closingFrame(
                    currentFrame: window.frame,
                    paneWidth: paneWidth,
                    minimumWindowWidth: baseContentMinSize.width
                ),
                display: true,
                animate: true
            )
        }
        paneWidth = 0
    }

    /// Called when the setup window closes: stops the embedded task view without touching the window.
    func tearDown() {
        removePane()
        paneWidth = 0
    }

    /// A collapsed setup window is a small bar, so the pane tucks away while it is collapsed and returns when the window expands.
    func windowCollapseChanged(isCollapsed: Bool) {
        guard isWindowCollapsed != isCollapsed else { return }
        isWindowCollapsed = isCollapsed
        guard let paneView else { return }
        paneView.isHidden = isCollapsed
        if isCollapsed {
            NSLayoutConstraint.deactivate(paneConstraints)
            setupFillsContainer.isActive = true
        } else {
            setupFillsContainer.isActive = false
            NSLayoutConstraint.activate(paneConstraints)
        }
    }

    private func removePane() {
        host?.tearDown()
        host = nil
        NSLayoutConstraint.deactivate(paneConstraints)
        paneConstraints.removeAll()
        paneView?.removeFromSuperview()
        paneView = nil
        setupFillsContainer.isActive = true
    }
}
