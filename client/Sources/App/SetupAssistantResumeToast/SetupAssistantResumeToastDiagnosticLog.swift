import Foundation

/// Diagnostic-only logging for the Setup Assistant resume toast's debug
/// menu path, kept in the same backend dev console (`DevLogger` ->
/// `APIClient.devLog` -> the backend's `[CLIENT]` log lines) you already
/// watch, rather than a separate unified-log stream.
///
/// `APIClient.devLog` rate-limits to 10 messages/second with no local
/// fallback when a message is dropped, which silently swallows most of a
/// same-tick instrumentation burst like `present()`'s (several log calls
/// fire back-to-back in one synchronous call stack). This queues messages
/// and drains them one at a time with spacing comfortably above that
/// throttle window, so every diagnostic line reaches the backend console
/// instead of being silently dropped -- at the cost of later lines lagging
/// real execution by a few hundred milliseconds, which is an acceptable
/// trade for a debug-only diagnostic aid.
@MainActor
final class SetupAssistantResumeToastDiagnosticLog {
    private enum Level {
        case info, warning, error
    }

    static let shared = SetupAssistantResumeToastDiagnosticLog()

    /// Comfortably above `APIClient`'s 100ms backend-log throttle window.
    private let spacingNanoseconds: UInt64 = 150_000_000
    private var queue: [(message: String, level: Level)] = []
    private var isDraining = false

    private init() {}

    static func info(_ message: String) {
        shared.enqueue(message, level: .info)
    }

    static func warning(_ message: String) {
        shared.enqueue(message, level: .warning)
    }

    static func error(_ message: String) {
        shared.enqueue(message, level: .error)
    }

    private func enqueue(_ message: String, level: Level) {
        queue.append((message, level))
        drainIfNeeded()
    }

    private func drainIfNeeded() {
        guard !isDraining else { return }
        isDraining = true
        Task { [weak self] in
            guard let self else { return }
            while true {
                guard !self.queue.isEmpty else {
                    self.isDraining = false
                    return
                }
                let next = self.queue.removeFirst()
                switch next.level {
                case .info:
                    DevLogger.shared.info(next.message, context: "SetupAssistant")
                case .warning:
                    DevLogger.shared.warning(next.message, context: "SetupAssistant")
                case .error:
                    DevLogger.shared.error(next.message, context: "SetupAssistant")
                }
                try? await Task.sleep(nanoseconds: self.spacingNanoseconds)
            }
        }
    }
}
