import AppKit
import Combine

/// Owns exactly one embedded `AgentTaskResultWebView`, hosted as a native
/// subview inside a `BasilBoardWebView`'s own `WKWebView`. Created by
/// `BasilBoardWebView` when the Agent Tasks tab activates AND the Board is
/// currently the authoritative presenter; torn down when the tab
/// deactivates OR the standalone widget becomes authoritative.
///
/// Mirrors `AgentTaskResultWidgetController`'s follow-up-capture,
/// new-capture, refinement, and detached-roots plumbing so the two
/// surfaces behave identically -- see that type's doc comment for the
/// shared architectural model. The two are intentionally NOT merged into
/// one shared base class: `AgentTaskResultWidgetController` owns an
/// `NSWindow` and window-delegate lifecycle that has no embedded
/// equivalent, and forcing a shared superclass would require abstracting
/// that away for no behavioral benefit. The duplication here is bounded
/// (follow-up/new-capture/refinement plumbing only) and each half is unit
/// tested independently.
@MainActor
final class AgentTaskResultEmbeddedHost: NSObject, AgentTaskResultDetachedRootsObserver {
    let webView: AgentTaskResultWebView
    private weak var hostView: NSView?
    private let clippingContainer = NSView()
    private var constraints: [NSLayoutConstraint] = []

    var isWebViewReady = false
    var pendingWebCommands: [AgentTaskResultWidgetController.PendingWebCommand] = []
    var focusedRowState: AgentTaskResultWidgetController.FocusedRowState?

    var followUpCaptureVM: AgentTaskCaptureViewModel?
    var followUpCancellables = Set<AnyCancellable>()
    let followUpCaptureOwnerID = UUID()
    var provisionalFailureObserver: NSObjectProtocol?

    /// Registered by `BasilBoardWebView` so `onStartNewAgentTaskCapture`
    /// can spawn the same global capture widget the standalone singleton
    /// uses -- see `AgentTaskResultWidgetWindowBuilder.swift`'s identical
    /// hook for the source of this pattern.
    var onStartNewAgentTaskCapture: ((_ preGeneratedId: String) -> Void)?
    var onStopNewAgentTaskCapture: (() -> Void)?
    var onCancelNewAgentTaskCapture: (() -> Void)?

    init(embeddingInto hostView: NSView, topInset: CGFloat, leadingInset: CGFloat, originatingWindow: NSWindow?) {
        self.webView = AgentTaskResultWebView()
        self.hostView = hostView
        super.init()

        webView.prepareEmbeddedPresentation()
        webView.initialSidebarExpanded = true
        AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost = self
        DetachedAgentTaskWindowManager.shared.addObserver(self)
        ensureProvisionalFailureObserver()

        webView.onReady = { [weak self] in self?.handleWebViewReady() }
        webView.onClose = {
            DevLogger.shared.error(
                "[AgentTaskResultEmbeddedHost] Unexpected closeWidget from embedded surface",
                context: "AgentTaskResult"
            )
        }
        webView.onMinimize = {
            DevLogger.shared.error(
                "[AgentTaskResultEmbeddedHost] Unexpected minimizeWidget from embedded surface",
                context: "AgentTaskResult"
            )
        }
        webView.onResize = { _ in
            // Embedded frame is fixed by Auto Layout; resize requests are
            // suppressed at the source in `useResultWidgetSizing`'s
            // `embedded` early-return, so this is a defensive no-op.
        }
        webView.onOpenDetachedAgentTask = { rootTaskId in
            DetachedAgentTaskWindowManager.shared.open(rootTaskId: rootTaskId, originatingWindow: originatingWindow)
        }
        webView.onOpenAgentTaskOrigin = { originType, originId in
            AgentTaskOriginNavigator.open(
                originType: originType,
                originId: originId,
                originatingWindow: originatingWindow
            )
        }
        webView.onAgentStatusChanged = { [weak self] agentTaskId, isProcessing, hasResult, _, supportsFollowUp in
            guard let self else { return }
            self.focusedRowState = AgentTaskResultWidgetController.FocusedRowState(
                agentTaskId: agentTaskId, isProcessing: isProcessing,
                hasResult: hasResult, supportsFollowUp: supportsFollowUp
            )
            AgentTaskResultPresentationCoordinator.shared.updateBoardFocusedRow(
                agentTaskId: agentTaskId, isProcessing: isProcessing,
                hasResult: hasResult, supportsFollowUp: supportsFollowUp
            )
            AgentTaskFollowUpFocusRegistry.shared.update(
                ownerID: self.followUpCaptureOwnerID, agentTaskId: agentTaskId,
                isProcessing: isProcessing, supportsFollowUp: supportsFollowUp
            )
        }
        webView.onStartFollowUpCapture = { [weak self] rootTaskId, previousTaskId in
            self?.handleFollowUpCaptureStart(rootTaskId: rootTaskId, previousTaskId: previousTaskId)
        }
        webView.onStopFollowUpCapture = { [weak self] in self?.handleFollowUpCaptureStop() }
        webView.onCancelFollowUpCapture = { [weak self] in self?.handleFollowUpCaptureCancel() }
        webView.onStartNewAgentTaskCapture = { [weak self] preGeneratedId in
            self?.onStartNewAgentTaskCapture?(preGeneratedId)
        }
        webView.onStopNewAgentTaskCapture = { [weak self] in self?.onStopNewAgentTaskCapture?() }
        webView.onCancelNewAgentTaskCapture = { [weak self] in self?.onCancelNewAgentTaskCapture?() }
        webView.onStartRefinementRecording = { [weak self] in self?.handleRefinementStart() }
        webView.onStopRefinementRecording = { [weak self] in self?.handleRefinementStop() }
        webView.onCancelRunningAgentTask = { agentTaskId in
            Task {
                do {
                    try await performAgentTaskRESTCancellation(agentTaskId: agentTaskId)
                    DevLogger.shared.info(
                        "[AGENT_TASK] Embedded REST cancellation acknowledged for \(agentTaskId)",
                        context: "AgentTaskResult"
                    )
                } catch {
                    DevLogger.shared.error(
                        "[AGENT_TASK] Embedded REST cancellation failed for \(agentTaskId): \(error)",
                        context: "AgentTaskResult"
                    )
                }
            }
        }
        webView.onReportAgentTaskCancellationStage = { agentTaskId, stage in
            DevLogger.shared.info(
                "[AGENT_TASK] Embedded cancellation stage=\(stage) task=\(agentTaskId)",
                context: "AgentTaskResult"
            )
        }

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
        // The Board owns the upper chrome and left tab rail. Preserve its
        // layered outer frame and bottom-right corner by clipping both
        // the containment view and the WebKit compositor's own backing layer.
        let c = [
            clippingContainer.topAnchor.constraint(equalTo: hostView.topAnchor, constant: topInset),
            clippingContainer.leadingAnchor.constraint(equalTo: hostView.leadingAnchor, constant: leadingInset),
            clippingContainer.trailingAnchor.constraint(equalTo: hostView.trailingAnchor, constant: -8),
            clippingContainer.bottomAnchor.constraint(equalTo: hostView.bottomAnchor, constant: -8),
            webView.webView.topAnchor.constraint(equalTo: clippingContainer.topAnchor),
            webView.webView.leadingAnchor.constraint(equalTo: clippingContainer.leadingAnchor),
            webView.webView.trailingAnchor.constraint(equalTo: clippingContainer.trailingAnchor),
            webView.webView.bottomAnchor.constraint(equalTo: clippingContainer.bottomAnchor),
        ]
        NSLayoutConstraint.activate(c)
        constraints = c

        AgentTaskFollowUpFocusRegistry.shared.register(ownerID: followUpCaptureOwnerID) { [weak self] rootTaskId in
            self?.startFollowUpCapture(rootTaskId: rootTaskId)
        }
        AgentTaskFollowUpFocusRegistry.shared.setPrimary(ownerID: followUpCaptureOwnerID)

        webView.loadContent()
    }

    func startFollowUpCapture(rootTaskId: String) {
        handleFollowUpCaptureStart(rootTaskId: rootTaskId, previousTaskId: rootTaskId)
    }

    /// Called by `BasilBoardWebView` from `deactivateBoardAgentTasksSurface`
    /// and from the coordinator observer when standalone becomes
    /// authoritative while this host is live. Idempotent.
    func tearDown() {
        if followUpCaptureVM != nil { handleFollowUpCaptureCancel() }
        AgentTaskFollowUpFocusRegistry.shared.clearPrimary(ownerID: followUpCaptureOwnerID)
        AgentTaskFollowUpFocusRegistry.shared.unregister(ownerID: followUpCaptureOwnerID)
        DetachedAgentTaskWindowManager.shared.removeObserver(self)
        if AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost === self {
            AgentTaskResultPresentationCoordinator.shared.activeEmbeddedHost = nil
        }
        if let observer = provisionalFailureObserver {
            NotificationCenter.default.removeObserver(observer)
            provisionalFailureObserver = nil
        }
        NSLayoutConstraint.deactivate(constraints)
        constraints.removeAll()
        webView.tearDown()
        webView.webView.removeFromSuperview()
        clippingContainer.removeFromSuperview()
    }

    func updateDetachedRoots(_ ids: [String]) {
        dispatchOrQueueWebCommand(.detachedRoots(rootTaskIds: ids))
    }
}
