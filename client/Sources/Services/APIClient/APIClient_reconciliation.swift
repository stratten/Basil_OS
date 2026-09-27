import Foundation

/// Lightweight lock-state summary for the Skill Reconciliation Workspace. The
/// heavy session interaction (hydrate/decide/commit) lives in the web app; the
/// native side only needs to start, poll status (for the Settings-reopen edge
/// case), and discard on close.
struct ReconciliationStatusDTO: Codable {
    let active: Bool
    let sessionId: String?
    let status: String?
    let pendingCount: Int
    let actionCount: Int
}

extension APIClient {
    /// Start a reconciliation session (activates the backend freeze gate).
    @discardableResult
    func startReconciliationSession() async throws -> Data {
        try await postForData("/memory/reconciliation/session")
    }

    /// Read whether a reconciliation workspace currently owns the skill state.
    func getReconciliationStatus() async throws -> ReconciliationStatusDTO {
        let data = try await get("/memory/reconciliation/session/status")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ReconciliationStatusDTO.self, from: data)
    }

    /// Discard the active session and release the gate (fired on window close).
    @discardableResult
    func discardReconciliationSession() async throws -> Data {
        try await postForData("/memory/reconciliation/session/discard")
    }
}
