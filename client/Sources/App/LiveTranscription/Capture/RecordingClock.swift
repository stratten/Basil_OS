import Foundation

/// Meeting-elapsed capture time for one recording part, excluding paused spans.
///
/// Read from CoreAudio and tap threads as well as the main actor, so every access is serialized by a lock. The clock uses monotonic system uptime rather than `Date()` so wall-clock adjustments never move the meeting timeline.
final class RecordingClock: @unchecked Sendable {
    static let markerIntervalSeconds: TimeInterval = 2.0

    private let lock = NSLock()
    private let now: () -> TimeInterval
    private var accumulatedSeconds: TimeInterval = 0
    private var runningSince: TimeInterval?
    private var hasStarted = false
    private var isStopped = false
    private var lastMarkerElapsed: [AudioSource: TimeInterval] = [:]

    init(now: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.now = now
    }

    func start() {
        lock.lock()
        defer { lock.unlock() }
        accumulatedSeconds = 0
        runningSince = now()
        hasStarted = true
        isStopped = false
        lastMarkerElapsed.removeAll()
    }

    func pause() {
        lock.lock()
        defer { lock.unlock() }
        guard !isStopped, let since = runningSince else { return }
        accumulatedSeconds += max(0, now() - since)
        runningSince = nil
    }

    func resume() {
        lock.lock()
        defer { lock.unlock() }
        guard hasStarted, !isStopped, runningSince == nil else { return }
        runningSince = now()
    }

    /// Freezes the elapsed value so post-stop work (for example the on-stop tail re-transcription) still reads the part's final length.
    func stop() {
        lock.lock()
        defer { lock.unlock() }
        if let since = runningSince {
            accumulatedSeconds += max(0, now() - since)
        }
        runningSince = nil
        isStopped = hasStarted
    }

    func elapsedSeconds() -> TimeInterval {
        lock.lock()
        defer { lock.unlock() }
        guard let since = runningSince else { return accumulatedSeconds }
        return accumulatedSeconds + max(0, now() - since)
    }

    var isRunning: Bool {
        lock.lock()
        defer { lock.unlock() }
        return runningSince != nil
    }

    var isPaused: Bool {
        lock.lock()
        defer { lock.unlock() }
        return hasStarted && !isStopped && runningSince == nil
    }

    /// Forget the last clock marker for a source so its next audio chunk carries a fresh marker (used after a socket sends its stream-timing control).
    func resetMarker(for source: AudioSource) {
        lock.lock()
        defer { lock.unlock() }
        lastMarkerElapsed[source] = nil
    }

    /// Returns true when a clock marker should precede the chunk that starts at `elapsed`, and records it; markers are spaced by `markerIntervalSeconds` per source.
    func claimMarker(for source: AudioSource, at elapsed: TimeInterval) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard runningSince != nil, elapsed.isFinite else { return false }
        if let last = lastMarkerElapsed[source], elapsed - last < Self.markerIntervalSeconds {
            return false
        }
        lastMarkerElapsed[source] = elapsed
        return true
    }
}
