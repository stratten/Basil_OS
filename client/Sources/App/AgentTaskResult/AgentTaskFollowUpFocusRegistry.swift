import Foundation

@MainActor
final class AgentTaskFollowUpFocusRegistry {
    static let shared = AgentTaskFollowUpFocusRegistry()

    private struct Owner {
        var agentTaskId: String?
        var supportsFollowUp = false
        var isProcessing = false
        let start: (String) -> Void
    }

    private var owners: [UUID: Owner] = [:]
    private var keyOwnerID: UUID?
    private var primaryOwnerID: UUID?

    func register(ownerID: UUID, start: @escaping (String) -> Void) {
        owners[ownerID] = Owner(start: start)
    }

    func unregister(ownerID: UUID) {
        owners.removeValue(forKey: ownerID)
        if keyOwnerID == ownerID {
            keyOwnerID = nil
        }
        if primaryOwnerID == ownerID {
            primaryOwnerID = nil
        }
    }

    func focus(ownerID: UUID) {
        guard owners[ownerID] != nil else { return }
        keyOwnerID = ownerID
    }

    func resignFocus(ownerID: UUID) {
        guard keyOwnerID == ownerID else { return }
        keyOwnerID = nil
    }

    func setPrimary(ownerID: UUID) {
        guard owners[ownerID] != nil else { return }
        primaryOwnerID = ownerID
    }

    func clearPrimary(ownerID: UUID) {
        guard primaryOwnerID == ownerID else { return }
        primaryOwnerID = nil
    }

    func update(
        ownerID: UUID,
        agentTaskId: String?,
        isProcessing: Bool,
        supportsFollowUp: Bool
    ) {
        guard var owner = owners[ownerID] else { return }
        owner.agentTaskId = agentTaskId
        owner.isProcessing = isProcessing
        owner.supportsFollowUp = supportsFollowUp
        owners[ownerID] = owner
    }

    func startFocusedFollowUp() -> Bool {
        if let keyOwnerID, let owner = owners[keyOwnerID] {
            return startFollowUp(for: owner)
        }

        if let primaryOwnerID, let owner = owners[primaryOwnerID] {
            return startFollowUp(for: owner)
        }

        return false
    }

    private func startFollowUp(for owner: Owner) -> Bool {
        guard owner.supportsFollowUp,
              !owner.isProcessing,
              let agentTaskId = owner.agentTaskId,
              !agentTaskId.isEmpty else {
            return false
        }

        owner.start(agentTaskId)
        return true
    }
}
