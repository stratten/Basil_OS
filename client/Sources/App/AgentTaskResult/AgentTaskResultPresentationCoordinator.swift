import Foundation

/// Identifies which UI surface currently has presentation authority for
/// Agent Task Result content.
enum AgentTaskResultPresentationOwner: Equatable {
    case standalone
    case board
}

/// Tracks which Agent Task Result surface -- the standalone
/// `AgentTaskResultWidgetController` panel or the (future) Board-owned
/// host -- is currently visible, and arbitrates which one is authoritative.
///
/// Rule (settled, do not re-litigate): a visible standalone widget is
/// always authoritative. The Board surface may only be authoritative when
/// the standalone widget is not visible. This coordinator is the single
/// place that rule is expressed; nothing else may re-derive it.
///
/// The standalone widget reports its visibility from
/// `AgentTaskResultWidgetController.show()` / `dismiss()` (in
/// `AgentTaskResultWidgetWindowBuilder.swift` and
/// `AgentTaskResultWidgetLifecycle.swift`). `BasilBoardWebView` reports the
/// Agent Tasks tab placeholder's mounted state via `registerBoardVisible`
/// / `unregisterBoardVisible`. No embedded `AgentTaskResultWebView` exists
/// in the Board yet -- the Board side is a placeholder that only shows
/// "loading" or "open in a separate window" -- so Board-visibility state
/// does not yet gate any real content; a later package replaces the
/// placeholder with an actual embedded host without changing this
/// arbitration contract.
@MainActor
final class AgentTaskResultPresentationCoordinator {
    static let shared = AgentTaskResultPresentationCoordinator()

    private(set) var isStandaloneVisible = false
    private(set) var isBoardVisible = false
    private var observers: [UUID: () -> Void] = [:]

    /// Weak handle to the one live embedded host, set by
    /// `AgentTaskResultEmbeddedHost.init`/`tearDown()`. `nil` whenever no
    /// Board window currently has the Agent Tasks tab mounted, or when the
    /// mount exists but has been torn down because the standalone widget
    /// became authoritative. Read by `AgentTaskResultPresentationRouter`
    /// and by `WebSocketService.getWidgetState()`.
    weak var activeEmbeddedHost: AgentTaskResultEmbeddedHost?

    /// Authoritative owner given current visibility, or `nil` when neither
    /// surface is on screen. Standalone always wins ties.
    var activePresenter: AgentTaskResultPresentationOwner? {
        if isStandaloneVisible { return .standalone }
        if isBoardVisible { return .board }
        return nil
    }

    private var boardFocusedRowState: AgentTaskResultWidgetController.FocusedRowState?

    /// Called by `AgentTaskResultEmbeddedHost` whenever its own
    /// `agentStatusChanged` bridge message fires, mirroring
    /// `AgentTaskResultWidgetController.updateFocusedRow`.
    func updateBoardFocusedRow(
        agentTaskId: String?,
        isProcessing: Bool,
        hasResult: Bool,
        supportsFollowUp: Bool
    ) {
        boardFocusedRowState = AgentTaskResultWidgetController.FocusedRowState(
            agentTaskId: agentTaskId,
            isProcessing: isProcessing,
            hasResult: hasResult,
            supportsFollowUp: supportsFollowUp
        )
    }

    /// The focused-row snapshot belonging to whichever surface
    /// `activePresenter` currently names. `nil` when neither surface is
    /// visible, or when the authoritative surface has no focused row yet.
    /// Replaces the previous hardcoded read of
    /// `AgentTaskResultWidgetController.shared?.focusedRowState` in
    /// `WebSocketService.getWidgetState()`.
    var authoritativeFocusedRowState: AgentTaskResultWidgetController.FocusedRowState? {
        switch activePresenter {
        case .standalone: return AgentTaskResultWidgetController.shared?.focusedRowState
        case .board: return boardFocusedRowState
        case nil: return nil
        }
    }

    private init() {}

    /// Called by `AgentTaskResultWidgetController.show()` once its panel
    /// has actually been created (not on the "already up, just refocus"
    /// path, which does not change visibility).
    func standaloneDidBecomeVisible() {
        isStandaloneVisible = true
        notifyObservers()
    }

    /// Called unconditionally at the top of
    /// `AgentTaskResultWidgetController.dismiss()`, including on its
    /// already-dismissed early-return path, so this state can never drift
    /// from the controller's actual `panel == nil` reality.
    func standaloneDidDismiss() {
        isStandaloneVisible = false
        notifyObservers()
    }

    /// Called by `BasilBoardWebView` when its Agent Tasks tab placeholder
    /// mounts (the `activateBoardAgentTasksSurface` bridge message).
    func registerBoardVisible() {
        isBoardVisible = true
        notifyObservers()
    }

    /// Called by `BasilBoardWebView` when its Agent Tasks tab placeholder
    /// unmounts (the `deactivateBoardAgentTasksSurface` bridge message).
    func unregisterBoardVisible() {
        isBoardVisible = false
        notifyObservers()
    }

    /// Registers a closure invoked after every state-changing call above,
    /// so a caller (currently `BasilBoardWebView`) can push a fresh
    /// availability value to its web layer whenever the other surface's
    /// visibility changes while it is registered. Calling this again with
    /// the same `id` replaces the previous closure, which is exactly what
    /// happens if `activateBoardAgentTasksSurface` is received twice
    /// without an intervening deactivate.
    func addObserver(id: UUID, onChange: @escaping () -> Void) {
        observers[id] = onChange
    }

    func removeObserver(id: UUID) {
        observers.removeValue(forKey: id)
    }

    private func notifyObservers() {
        for observer in observers.values {
            observer()
        }
    }

    /// Test-only reset so coordinator tests don't leak state into each
    /// other via the shared singleton.
    #if DEBUG
    func resetForTesting() {
        isStandaloneVisible = false
        isBoardVisible = false
        boardFocusedRowState = nil
        activeEmbeddedHost = nil
        observers.removeAll()
    }
    #endif
}
