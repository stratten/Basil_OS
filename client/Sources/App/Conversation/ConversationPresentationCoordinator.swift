import Foundation

/// Identifies the visible surface that owns Conversation presentation.
enum ConversationPresentationOwner: Equatable {
    case standalone
    case board
}

/// Owns the single Conversation presentation-authority rule.
///
/// A visible standalone window always wins. The future Board integration only
/// registers its visibility here; it must not reproduce this priority rule.
@MainActor
final class ConversationPresentationCoordinator {
    static let shared = ConversationPresentationCoordinator()

    private var standaloneLeases: Set<UUID> = []
    private var globalStandaloneLease: UUID?
    var isStandaloneVisible: Bool { !standaloneLeases.isEmpty }
    private(set) var isBoardVisible = false
    private var observers: [UUID: () -> Void] = [:]

    /// Returns the authoritative surface for the current visibility state.
    /// Standalone wins whenever both surfaces are visible.
    var activePresenter: ConversationPresentationOwner? {
        if isStandaloneVisible { return .standalone }
        if isBoardVisible { return .board }
        return nil
    }

    private init() {}

    /// Records that the native standalone Conversation window is visible.
    /// This remains idempotent because native show requests may focus an
    /// already-visible window.
    func standaloneDidBecomeVisible() {
        guard globalStandaloneLease == nil else { return }
        globalStandaloneLease = acquireStandaloneLease()
    }

    /// Records that the native standalone Conversation window is hidden.
    /// This remains idempotent because close and hide paths can converge.
    func standaloneDidDismiss() {
        guard let globalStandaloneLease else { return }
        releaseStandaloneLease(globalStandaloneLease)
        self.globalStandaloneLease = nil
    }

    func acquireStandaloneLease() -> UUID {
        let lease = UUID()
        standaloneLeases.insert(lease)
        notifyObservers()
        return lease
    }

    func releaseStandaloneLease(_ lease: UUID) {
        guard standaloneLeases.remove(lease) != nil else { return }
        notifyObservers()
    }

    /// Reserves the Board visibility producer for the next plan. It does not
    /// create, mount, or otherwise control a Board surface itself.
    func registerBoardVisible() {
        guard !isBoardVisible else { return }
        isBoardVisible = true
        notifyObservers()
    }

    /// Clears the Board visibility producer when that future surface unmounts.
    func unregisterBoardVisible() {
        guard isBoardVisible else { return }
        isBoardVisible = false
        notifyObservers()
    }

    /// Registers one observer closure per identifier. Reusing an identifier
    /// replaces its prior closure so repeated surface activation cannot leak
    /// duplicate observers.
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

    /// Isolates the shared singleton between DEBUG XCTest cases.
    #if DEBUG
    func resetForTesting() {
        standaloneLeases.removeAll()
        globalStandaloneLease = nil
        isBoardVisible = false
        observers.removeAll()
    }
    #endif
}
