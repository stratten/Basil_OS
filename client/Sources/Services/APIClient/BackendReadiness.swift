import Foundation

/// Waits for the backend to answer, with no deadline.
///
/// Backend startup can take minutes (loading local models, clearing a leftover process, a slow disk). A caller that gave up after a fixed time left its feature unconfigured for the whole session, so callers wait until the backend answers or the app is going away.
enum BackendReadiness {
    /// Polls `probe` until it reports the backend is available. Returns `false` only when `shouldStop` says to stop waiting, never because time ran out.
    static func wait(
        pollInterval: TimeInterval,
        probe: () async -> Bool,
        shouldStop: () -> Bool
    ) async -> Bool {
        while !shouldStop() {
            if await probe() { return true }
            try? await Task.sleep(nanoseconds: UInt64(pollInterval * 1_000_000_000))
        }
        return false
    }
}

extension APIClient {
    /// Suspends until the shared backend answers `/health`, checking again every `pollInterval` seconds.
    ///
    /// `isBackendAvailable` is only refreshed when something calls `updatePortAndCheckStatus()`, so this probes the backend itself on each pass instead of reading a flag that nothing else may update while the app sits idle. The probe also follows the backend's port file, which matters when a restarted backend picks a new port.
    ///
    /// Returns `false` only when the waiting task is canceled or the app is quitting.
    static func waitUntilBackendAvailable(pollInterval: TimeInterval = 1.0) async -> Bool {
        await BackendReadiness.wait(
            pollInterval: pollInterval,
            probe: {
                let api = APIClient.shared
                if !api.isBackendAvailable { await api.updatePortAndCheckStatus() }
                return api.isBackendAvailable
            },
            shouldStop: { Task.isCancelled || APIClient.isBackendShuttingDown }
        )
    }
}
