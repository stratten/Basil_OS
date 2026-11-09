import Foundation

/// What the microphone watchdog should do about a microphone that is delivering buffers full of exact zeros.
enum SilentInputAction: Equatable {
    /// Nothing to do yet: the input has heard signal, has not been silent long enough, or is waiting out the gap after a reclaim attempt.
    case none
    /// Rebuild the microphone engine to try to take the input back from whatever is holding it.
    case reclaim
}

/// When to retry a silent microphone and when to tell the user it could not be taken back.
///
/// A call app such as WhatsApp can put a voice processor on the built-in microphone, after which macOS keeps calling a recorder's tap on schedule but fills every buffer with zeros. The existing stall watchdog never sees this because buffers keep arriving. The recorder retries the input a few times, then warns, then keeps retrying more slowly in case the call app lets go.
struct SilentInputPolicy: Equatable {
    /// Continuous digital silence, in seconds, that triggers a reclaim attempt before the warning is up.
    var silenceBeforeReclaim: TimeInterval = 8
    /// Reclaim attempts that must leave the input silent before the user is warned.
    var attemptsBeforeWarning = 3
    /// Continuous digital silence, in seconds, between reclaim attempts once the warning is up, so a call that holds the microphone for a long time is not rebuilt every few seconds.
    var silenceBeforeReclaimWhileWarning: TimeInterval = 30

    /// Whether the user should currently be warned. Requires the input to have stayed silent for a full `silenceBeforeReclaim` after the last attempt, so a reclaim that is still starting up does not raise the warning.
    func shouldWarn(silentFor: TimeInterval?, attempts: Int) -> Bool {
        guard let silentFor else { return false }
        return attempts >= attemptsBeforeWarning && silentFor >= silenceBeforeReclaim
    }

    func action(silentFor: TimeInterval?, attempts: Int) -> SilentInputAction {
        guard let silentFor else { return .none }
        let threshold = attempts >= attemptsBeforeWarning ? silenceBeforeReclaimWhileWarning : silenceBeforeReclaim
        return silentFor >= threshold ? .reclaim : .none
    }
}

/// Measures how long the microphone has delivered nothing but digital silence.
///
/// Real microphones never produce sustained exact zeros: the preamp and converter noise floor always shows up in the samples. A buffer of exact zeros therefore means the input is being withheld or muted, not that the room is quiet.
///
/// The tap callback runs on a real-time audio thread while the watchdog runs on the main actor, so all state is guarded by a lock. The critical sections only read and write a few values, which keeps `markBuffer(isSilent:)` safe to call from the audio thread.
final class SilentInputTracker: @unchecked Sendable {
    private let lock = NSLock()
    private let clock: () -> TimeInterval
    private var isArmed = false
    private var silentSince: TimeInterval?
    private var heardSignal = false

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
    }

    /// Starts watching a freshly started engine, forgetting anything heard from the previous one.
    func arm() {
        lock.lock()
        defer { lock.unlock() }
        isArmed = true
        silentSince = nil
        heardSignal = false
    }

    /// Stops watching, for example while capture is paused or the engine is torn down.
    func disarm() {
        lock.lock()
        defer { lock.unlock() }
        isArmed = false
        silentSince = nil
        heardSignal = false
    }

    /// Records one delivered buffer. A silent buffer starts the silence clock if it is not already running, and any buffer with signal stops it.
    func markBuffer(isSilent: Bool) {
        let now = clock()
        lock.lock()
        defer { lock.unlock() }
        guard isArmed else { return }
        if isSilent {
            if silentSince == nil { silentSince = now }
        } else {
            silentSince = nil
            heardSignal = true
        }
    }

    /// Seconds of unbroken digital silence up to now, or `nil` when the input is not currently silent or not armed.
    func silenceDuration() -> TimeInterval? {
        lock.lock()
        defer { lock.unlock() }
        guard isArmed, let silentSince else { return nil }
        return max(0, clock() - silentSince)
    }

    /// Whether any buffer with signal has arrived since the tracker was armed. The watchdog uses this to tell a reclaim that worked from one whose first buffers simply have not arrived yet.
    var hasHeardSignalSinceArming: Bool {
        lock.lock()
        defer { lock.unlock() }
        return isArmed && heardSignal
    }

    /// Whether every sample in a converted buffer is exactly zero. An empty buffer is not treated as silent, because it carries no evidence either way.
    static func isDigitalSilence(_ samples: UnsafeBufferPointer<Int16>) -> Bool {
        guard !samples.isEmpty else { return false }
        for sample in samples where sample != 0 { return false }
        return true
    }
}
