import Foundation
import os

/// Measures where the time goes between a hotkey press and a usable agent task capture input.
///
/// `begin()` starts a measurement and each `mark(_:)` records the elapsed milliseconds since then. Marks made while no measurement has begun are dropped, so call sites that are shared with other flows, such as `WindowCaptureService.captureActiveWindow`, cost nothing outside a hotkey capture.
///
/// Every mark is emitted as an `os_signpost` event in the `AgentTaskCaptureLatency` category for Instruments. In DEBUG builds each mark is also written to `DevLogger`, which reaches the backend console and the log relay.
final class AgentTaskCaptureLatencyTrace: @unchecked Sendable {
    enum Mark: String, CaseIterable {
        case widgetRequested
        case panelShown
        case navigationCommitted
        case navigationFinished
        case reactReady
        case backendResponded
        case backendEventReceived
        case windowCaptureStarted
        case windowCaptureFinished
    }

    static let shared = AgentTaskCaptureLatencyTrace()

    private let lock = NSLock()
    private let uptimeNanoseconds: () -> UInt64
    private let sink: (String) -> Void
    private var originNanoseconds: UInt64?
    private let signposter = OSSignposter(subsystem: "com.stratten.basil", category: "AgentTaskCaptureLatency")

    init(
        uptimeNanoseconds: @escaping () -> UInt64 = { DispatchTime.now().uptimeNanoseconds },
        sink: @escaping (String) -> Void = AgentTaskCaptureLatencyTrace.logToDevLogger
    ) {
        self.uptimeNanoseconds = uptimeNanoseconds
        self.sink = sink
    }

    static func logToDevLogger(_ line: String) {
        #if DEBUG
        DevLogger.shared.info(line, context: "AgentTaskCaptureLatency")
        #endif
    }

    /// Starts a new measurement, discarding any measurement already in progress.
    func begin() {
        lock.lock()
        originNanoseconds = uptimeNanoseconds()
        lock.unlock()
        signposter.emitEvent("AgentTaskCaptureBegin")
        sink("[AgentTaskCaptureLatency] +0ms begin")
    }

    /// Records one stage. Returns the elapsed milliseconds since `begin()`, or nil when no measurement is in progress.
    @discardableResult
    func mark(_ mark: Mark) -> Int? {
        lock.lock()
        let now = uptimeNanoseconds()
        let origin = originNanoseconds
        lock.unlock()
        guard let origin else { return nil }
        let elapsedMilliseconds = now >= origin ? Int((now - origin) / 1_000_000) : 0
        signposter.emitEvent("AgentTaskCaptureMark", "\(mark.rawValue, privacy: .public)")
        sink("[AgentTaskCaptureLatency] +\(elapsedMilliseconds)ms \(mark.rawValue)")
        return elapsedMilliseconds
    }
}
