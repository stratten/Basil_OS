import AppKit
import Foundation

/// Wires the floating ``ScheduledRunMiniPanelWindowController`` into the
/// AppDelegate lifecycle.
///
/// Responsibilities:
///   * Lazily create the controller the first time anything wants it.
///   * Listen on ``NSNotification.Name("BasilScheduledAgentTaskWSEvent")``
///     (posted by ``WebSocketService`` for ``scheduled_agent_task_run_started``,
///     ``scheduled_agent_task_run_completed``, and ``scheduled_agent_task_missed``)
///     and use ``run_started`` to drive ``orderFrontIfHidden()``. The other
///     two are forwarded to the WKWebView indirectly via its own WS connection
///     so we don't double-handle them here.
///   * Forward ``onOpenAgentTask`` row clicks through
///     ``AgentTaskResultPresentationRouter.showExistingAgentTask(...)`` so
///     the task appears in the authoritative Board or standalone surface.
extension AppDelegate {

    private static let scheduledRunWSEventName = NSNotification.Name("BasilScheduledAgentTaskWSEvent")

    /// Lazily instantiate the controller. Safe to call multiple times.
    @MainActor
    func ensureScheduledRunMiniPanelController() -> ScheduledRunMiniPanelWindowController {
        if let existing = scheduledRunMiniPanelController {
            return existing
        }
        let controller = ScheduledRunMiniPanelWindowController()
        controller.onOpenAgentTask = { [weak self] agentTaskId, _ in
            self?.handleScheduledRunRowClick(agentTaskId: agentTaskId)
        }
        scheduledRunMiniPanelController = controller
        return controller
    }

    /// Subscribe the AppDelegate to scheduled-agent-task WS events. Idempotent —
    /// safe to call multiple times; the second call is a no-op because the
    /// observer token tracks whether we've already wired up.
    ///
    /// Implementation note: the closure intentionally re-derives the
    /// AppDelegate via ``NSApplication.shared.delegate`` rather than
    /// capturing ``self`` weakly. NotificationCenter callbacks are typed
    /// ``@Sendable`` and ``AppDelegate`` is a non-Sendable NSObject subclass,
    /// so a weak-self capture trips a Swift 5.10 Sendable warning. The
    /// re-derive sidesteps that without changing observable behavior — the
    /// AppDelegate is process-singleton.
    @MainActor
    func registerScheduledRunMiniPanelObserver() {
        guard scheduledRunMiniPanelObserverToken == nil else { return }
        let token = NotificationCenter.default.addObserver(
            forName: AppDelegate.scheduledRunWSEventName,
            object: nil,
            queue: .main
        ) { note in
            guard let json = note.userInfo as? [String: Any] else { return }
            guard let eventType = json["event_type"] as? String else { return }
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                appDelegate.handleScheduledRunWSEvent(eventType: eventType, json: json)
            }
        }
        scheduledRunMiniPanelObserverToken = token

        #if DEBUG
        DevLogger.shared.info("[ScheduledRunMiniPanel] AppDelegate observer registered for scheduled-agent-task WS events", context: "ScheduledRunMiniPanel")
        #endif
    }

    @MainActor
    private func handleScheduledRunWSEvent(eventType: String, json: [String: Any]) {
        switch eventType {
        case "scheduled_agent_task_run_started":
            // Auto-show the mini panel if it isn't already visible. The React
            // app inside the panel will pick up the same WS event over its
            // own connection and render the row; we're only responsible for
            // making sure the host NSPanel is on screen.
            let controller = ensureScheduledRunMiniPanelController()
            controller.orderFrontIfHidden()

        case "scheduled_agent_task_run_completed", "scheduled_agent_task_missed":
            // Nothing to do at the AppDelegate level — the panel's own WS
            // listener handles row updates and the result widget displays
            // missed-run toasts on its own.
            break

        default:
            break
        }
    }

    @MainActor
    private func handleScheduledRunRowClick(agentTaskId: String) {
        guard !agentTaskId.isEmpty else { return }

        // Anchor the result widget to the capture widget if one happens to
        // be on screen (e.g., user clicked a scheduled-run row mid-capture).
        // Otherwise the singleton falls back to its standalone top-right
        // monitor positioning.
        let anchorFrame = AgentTaskCaptureInputWindowController.activeController?.panel?.frame

        AgentTaskResultPresentationRouter.showExistingAgentTask(
            agentTaskId: agentTaskId,
            anchorFrame: anchorFrame
        )
        NSApp.activate(ignoringOtherApps: true)
    }
}
