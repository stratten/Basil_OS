import Foundation

/// Makes sure a feature the person set to start at launch is really running, rather than trying once and forgetting.
///
/// Meeting Detection and Activity Capture used to be asked to start a single time after a fixed wait. A backend that was slow, a settings read that failed, or a start request that was refused left the feature off for the whole session with only a log line. This keeps checking: it reads the setting, looks at whether the feature is already running, starts it when it is not, and confirms it is running afterward. When any step fails or the confirmation does not come, it waits and tries the whole sequence again.
enum StartupFeatureAutostart {
    enum Outcome: Equatable {
        /// Confirmed running, either already or after a start.
        case running
        /// The settings say it should not start at launch (off, or "start at startup" off), so nothing was started.
        case notWanted
        /// Every attempt ran and the feature was still not confirmed running.
        case gaveUp
        /// The app is quitting or the task was canceled.
        case stopped
    }

    /// Waits before the second, third, and later attempts. About five minutes in all, long enough for a backend that is still loading local models, short enough not to retry forever on a feature that cannot start.
    static let defaultRetryDelays: [TimeInterval] = [2, 5, 10, 20, 30, 30, 30, 30, 30, 30, 30, 30]

    static func ensureRunning(
        name: String,
        shouldRun: () async throws -> Bool,
        isRunning: () async throws -> Bool,
        start: () async throws -> Void,
        retryDelays: [TimeInterval] = defaultRetryDelays,
        shouldStop: () -> Bool = { Task.isCancelled || APIClient.isBackendShuttingDown },
        pause: (TimeInterval) async -> Void = { delay in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        },
        log: (String) -> Void = { _ in }
    ) async -> Outcome {
        var attempt = 0
        while true {
            if shouldStop() { return .stopped }
            do {
                guard try await shouldRun() else { return .notWanted }
                if try await isRunning() { return .running }
                try await start()
                if try await isRunning() { return .running }
                log("\(name) did not report running after it was asked to start (attempt \(attempt + 1)).")
            } catch {
                log("\(name) could not be started at launch (attempt \(attempt + 1)): \(error.localizedDescription)")
            }
            guard attempt < retryDelays.count else {
                log("\(name) is set to start at launch but could not be confirmed running after \(attempt + 1) attempts.")
                return .gaveUp
            }
            await pause(retryDelays[attempt])
            attempt += 1
        }
    }
}
