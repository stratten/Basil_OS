import Foundation

/// Detects a capture engine that is "running" but delivering no audio.
///
/// After an input-device change `AVAudioEngine` can restart without error and then never call its tap again, so nothing downstream sees a failure: the socket stays up and the recording continues with a silent gap. This tracker records when capture was armed and when the last buffer arrived, so a watchdog can tell a live engine from a stalled one.
///
/// The tap callback runs on a real-time audio thread while the watchdog runs on the main actor, so all state is guarded by a lock. The critical sections only read and write two doubles, which keeps `markActivity()` safe to call from the audio thread.
final class CaptureLivenessTracker: @unchecked Sendable {
    private let lock = NSLock()
    private let clock: () -> TimeInterval
    private var armedAt: TimeInterval?
    private var lastActivityAt: TimeInterval?

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
    }

    /// Starts watching a freshly started engine. Time-to-first-buffer counts as a stall just like a gap between buffers.
    func arm() {
        lock.lock()
        defer { lock.unlock() }
        armedAt = clock()
        lastActivityAt = nil
    }

    /// Stops watching, for example while capture is paused or the engine is torn down.
    func disarm() {
        lock.lock()
        defer { lock.unlock() }
        armedAt = nil
        lastActivityAt = nil
    }

    /// Records that the capture callback delivered a buffer.
    func markActivity() {
        let now = clock()
        lock.lock()
        defer { lock.unlock() }
        guard armedAt != nil else { return }
        lastActivityAt = now
    }

    /// Seconds since the last buffer, or since arming if none has arrived yet; `nil` when not armed.
    func stallDuration() -> TimeInterval? {
        lock.lock()
        defer { lock.unlock() }
        guard let armedAt else { return nil }
        return max(0, clock() - (lastActivityAt ?? armedAt))
    }

    /// Whether at least one buffer has arrived since the tracker was armed.
    var hasReceivedActivitySinceArming: Bool {
        lock.lock()
        defer { lock.unlock() }
        return armedAt != nil && lastActivityAt != nil
    }
}
