import Foundation

/// Owns the single Skill Reconciliation Workspace window. Launching while one is
/// already open just focuses it (single active session). On close it defensively
/// posts /session/discard (releasing the backend freeze gate) and forwards the
/// onClose callback so Settings can unlock and refresh.
@MainActor
final class ReconciliationWorkspaceLauncher {
    static let shared = ReconciliationWorkspaceLauncher()

    private var controller: ReconciliationWorkspaceWindowController?

    private init() {}

    var isOpen: Bool { controller != nil }

    func open(onClose: @escaping () -> Void) {
        if let controller {
            controller.focus()
            return
        }
        var created: ReconciliationWorkspaceWindowController!
        created = ReconciliationWorkspaceWindowController { [weak self] in
            self?.controller = nil
            Task { try? await APIClient.shared.discardReconciliationSession() }
            onClose()
        }
        controller = created
        created.show()
    }

    /// Bring the live workspace window forward (used by the Settings "Show
    /// Workspace" button). No-op when the window is already closed, since the
    /// lock — and therefore that button — is only present while it is open.
    func focusOrReopen() {
        controller?.focus()
    }
}
