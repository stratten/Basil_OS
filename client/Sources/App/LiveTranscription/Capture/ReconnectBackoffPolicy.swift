import Foundation

/// Pure backoff and give-up policy for WebSocket reconnect attempts.
enum ReconnectBackoffPolicy {
    /// Stop retrying after this many failed connection attempts.
    static let maxAttempts = 6

    /// Exponential delays of 1, 2, 4, 8, 16, and 30 seconds.
    static func delaySeconds(forAttempt attempt: Int) -> Double {
        guard attempt > 0 else { return 0 }
        let exponent = min(attempt - 1, 5)
        return min(Double(1 << exponent), 30)
    }

    static func shouldGiveUp(afterAttempt attempt: Int) -> Bool {
        attempt >= maxAttempts
    }
}
