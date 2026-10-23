import Foundation

@MainActor
final class AgentTaskFollowUpCaptureLease {
    static let shared = AgentTaskFollowUpCaptureLease()

    private(set) var ownerID: UUID?
    private var completeAction: (() -> Void)?
    private var cancelAction: (() -> Void)?

    func acquire(
        ownerID: UUID,
        onComplete: @escaping () -> Void,
        onCancel: @escaping () -> Void
    ) -> Bool {
        guard self.ownerID == nil else { return false }
        self.ownerID = ownerID
        completeAction = onComplete
        cancelAction = onCancel
        return true
    }

    func release(ownerID: UUID) {
        guard self.ownerID == ownerID else { return }
        self.ownerID = nil
        completeAction = nil
        cancelAction = nil
    }

    func completeActiveCapture() -> Bool {
        guard let completeAction else { return false }
        completeAction()
        return true
    }

    func cancelActiveCapture() -> Bool {
        guard let cancelAction else { return false }
        cancelAction()
        return true
    }
}
