import AppKit
import Combine

/// Self-owning singleton for the persistent AgentTask result/history widget.
///
/// Architectural model (per user-clarified gates):
///
/// * The result widget and the history widget are the SAME thing — one
///   container that shows history rows, scheduling entries, and the
///   currently-running agent's progress/output. Only ONE may exist on
///   screen at a time; this singleton enforces that invariant.
/// * Lifecycle is INDEPENDENT of any capture controller. The singleton
///   retains itself via ``shared`` while alive; closing the panel
///   (close button, Cmd+W from inside, or any explicit ``dismiss()``
///   call) clears ``shared`` and releases the panel and webview together.
/// * The capture widget (``AgentTaskCaptureWindowController``) is used
///   ONLY for capturing brand-new AgentTasks — initial hotkey/voice
///   triggers, or the "new AgentTask" affordance inside this widget. It
///   never hosts results or history.
/// * Follow-up captures (against an in-widget row) NEVER spawn a
///   capture widget. Their audio capture VM is owned right here on the
///   singleton; the React UI renders the inline recording bar.
/// * On capture completion the capture widget closes; its WS-driven
///   processing/output streams into THIS widget. If this widget didn't
///   exist before capture completion it is created now via
///   ``installNewAgent(agentTaskId:initialAgentTask:anchorFrame:)``; if it
///   did, the new agent is registered and focused via the JS bridge.
///
/// The agentTask hotkey handler reads ``focusedRowState`` (pushed from JS
/// via the ``agentStatusChanged`` bridge message) to decide whether to
/// start a follow-up against the currently selected row or kick off a
/// fresh capture through the capture widget.
@MainActor
final class AgentTaskResultWidgetController: NSObject, NSWindowDelegate, AgentTaskResultDetachedRootsObserver {
    // MARK: - Singleton

    /// Strong, self-retained reference. Set in ``ensureShared()``.
    /// Cleared by ``dismiss()``. Other code accesses but does not retain.
    static var shared: AgentTaskResultWidgetController?

    // MARK: - Focused row state cache

    var focusedRowState: FocusedRowState?

    func updateFocusedRow(
        agentTaskId: String?,
        isProcessing: Bool,
        hasResult: Bool,
        supportsFollowUp: Bool
    ) {
        focusedRowState = FocusedRowState(
            agentTaskId: agentTaskId,
            isProcessing: isProcessing,
            hasResult: hasResult,
            supportsFollowUp: supportsFollowUp
        )
    }

    // MARK: - External callback hooks (NEW-AGENTTASK-CAPTURE only)

    /// Registered by the bootstrapping coordinator. Invoked when the
    /// React UI requests a brand-new AgentTask capture from inside the
    /// result widget (i.e. the "+ new AgentTask" affordance on a row that
    /// can't receive a follow-up). The handler is expected to spawn a
    /// fresh capture widget via ``StatusBarWindowCoordinator`` — exactly
    /// the same path a hotkey-initiated new capture takes.
    ///
    /// Follow-up captures, refinement captures, and cancel-running are
    /// handled INTERNALLY by this singleton; no external hook needed.
    var onStartNewAgentTaskCapture: ((_ preGeneratedId: String) -> Void)?
    var onStopNewAgentTaskCapture: (() -> Void)?
    var onCancelNewAgentTaskCapture: (() -> Void)?

    // MARK: - Window state

    var panel: NSWindow?
    var webView: AgentTaskResultWebView?
    var collapseController: WindowCollapseController?
    var isWebViewReady = false
    var pendingWebCommands: [PendingWebCommand] = []
    var lastKnownDetachedRoots: [String] = []

    /// Per-window local key monitor that translates Cmd+W (and Cmd+M)
    /// into `window.close()` / `window.miniaturize(_:)`. The app's main
    /// menu wires `File > Close Window` to `performClose:` with a nil
    /// target, but borderless windows fail AppKit's `performClose:`
    /// menu validation (no `.closable` style mask, no close button to
    /// "perform" against), so the key equivalent drops silently. This
    /// helper bypasses that validation by listening for the keystroke
    /// directly while the window is key. The same helper is used by
    /// every other working borderless window in the app
    /// (`Conversation`, `AssistantSession`, `AssistantOutputHistory`); the result
    /// widget was the lone holdout.
    var keyboardShortcuts: WindowKeyboardShortcuts?

    var isVisible: Bool { panel?.isVisible == true }
    var isMiniaturized: Bool { panel?.isMiniaturized == true }

    /// Convenience for callers that want to anchor a sibling widget
    /// (the capture widget) relative to the result/history panel.
    var panelFrame: NSRect? { panel?.frame }

    func updateDetachedRoots(_ ids: [String]) {
        lastKnownDetachedRoots = ids
        dispatchOrQueueWebCommand(.detachedRoots(rootTaskIds: ids))
    }

    // MARK: - Internal follow-up capture

    /// Audio capture VM for an in-widget follow-up. Created on
    /// ``handleFollowUpCaptureStart`` and cleared on completion or
    /// cancellation. Lives here (not on the capture controller) because
    /// follow-ups never surface a capture widget — the React UI in this
    /// singleton's webview hosts the recording bar.
    var followUpCaptureVM: AgentTaskCaptureViewModel?
    var followUpCancellables = Set<AnyCancellable>()
    let followUpCaptureOwnerID = UUID()

    /// Notification observer for ``AgentTaskCaptureViewModel``'s
    /// provisional-failure post. Installed lazily the first time
    /// ``ensureProvisionalFailureObserver`` is called and persists for the
    /// lifetime of the singleton (cleared on ``dismiss``). Forwards each
    /// failure into the React webview so the transient row (registered via
    /// ``sendRegisterAndSelectAgent`` at capture-handoff) can be removed
    /// instead of polling a never-persisted ID until 404s.
    var provisionalFailureObserver: NSObjectProtocol?
}
