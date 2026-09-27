import Foundation

/// Identifies which UI surface currently has presentation authority for the
/// Meeting Assistant.
enum MeetingPresentationOwner: Equatable {
    case standalone
    case board
}

/// Tracks which Meeting Assistant surface -- the standalone
/// `MeetingAssistantWindowController` panel (opened from the status-bar menu,
/// meeting detection, or calendar context) or the Board-owned
/// `MeetingAssistantEmbeddedHost` -- is currently visible, and arbitrates
/// which one is authoritative.
///
/// Rule (settled, mirrors `AgentTaskResultPresentationCoordinator`): a
/// visible standalone window is always authoritative. The Board surface may
/// only be authoritative when the standalone window is not visible. Both
/// surfaces attach to the same shared `LiveTranscriptionViewModel` via
/// `MeetingSessionCoordinator`, so this coordinator's job is purely about
/// which surface is allowed to be on screen at once -- never about which one
/// owns the underlying session data.
@MainActor
final class MeetingPresentationCoordinator {
    static let shared = MeetingPresentationCoordinator()

    private(set) var isStandaloneVisible = false
    private(set) var isBoardVisible = false
    private var observers: [UUID: () -> Void] = [:]

    /// Weak handle to the one live embedded host, set by
    /// `MeetingAssistantEmbeddedHost.init`/`tearDown()`. `nil` whenever no
    /// Board window currently has the Meetings tab mounted, or when the
    /// mount exists but has been torn down because the standalone window
    /// became authoritative. Read by `MeetingSessionCoordinator.showWebMeeting()`
    /// to raise the Board's window instead of opening a redundant standalone
    /// one.
    weak var activeEmbeddedHost: MeetingAssistantEmbeddedHost?

    /// Authoritative owner given current visibility, or `nil` when neither
    /// surface is on screen. Standalone always wins ties.
    var activePresenter: MeetingPresentationOwner? {
        if isStandaloneVisible { return .standalone }
        if isBoardVisible { return .board }
        return nil
    }

    private init() {}

    /// Called by `MeetingAssistantWindowController.show()` once its panel
    /// has actually been created (not on the "already up, just refocus"
    /// path, which does not change visibility).
    func standaloneDidBecomeVisible() {
        isStandaloneVisible = true
        notifyObservers()
    }

    /// Called unconditionally at the top of
    /// `MeetingAssistantWindowController`'s teardown, including on its
    /// already-dismissed early-return path, so this state can never drift
    /// from the controller's actual `panel == nil` reality.
    func standaloneDidDismiss() {
        isStandaloneVisible = false
        notifyObservers()
    }

    /// Called by `BasilBoardWebView` when its Meetings tab mounts (the
    /// `activateBoardMeetingsSurface` bridge message).
    func registerBoardVisible() {
        isBoardVisible = true
        notifyObservers()
    }

    /// Called by `BasilBoardWebView` when its Meetings tab unmounts (the
    /// `deactivateBoardMeetingsSurface` bridge message).
    func unregisterBoardVisible() {
        isBoardVisible = false
        notifyObservers()
    }

    /// Registers a closure invoked after every state-changing call above, so
    /// a caller (currently `BasilBoardWebView`) can reconcile its embedded
    /// host and push a fresh availability value to its web layer whenever
    /// the other surface's visibility changes while it is registered.
    /// Calling this again with the same `id` replaces the previous closure.
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

    /// Test-only reset so coordinator tests don't leak state into each other
    /// via the shared singleton.
    #if DEBUG
    func resetForTesting() {
        isStandaloneVisible = false
        isBoardVisible = false
        activeEmbeddedHost = nil
        observers.removeAll()
    }
    #endif
}
