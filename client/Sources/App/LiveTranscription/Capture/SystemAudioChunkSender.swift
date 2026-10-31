import Foundation

/// Destination for system-audio frames. `URLSessionWebSocketTask` conforms; tests supply a fake.
protocol SystemAudioChunkTransport: AnyObject {
    func sendMarker(_ text: String)
    func sendChunk(_ data: Data, completion: @escaping @Sendable (Error?) -> Void)
}

extension URLSessionWebSocketTask: SystemAudioChunkTransport {
    func sendMarker(_ text: String) {
        send(.string(text)) { _ in }
    }

    func sendChunk(_ data: Data, completion: @escaping @Sendable (Error?) -> Void) {
        send(.data(data), completionHandler: completion)
    }
}

/// Converts captured system-audio float samples to 16 kHz Int16 chunks and sends them over the system-audio WebSocket without involving the main thread.
///
/// Captured audio used to hop to the main thread twice (once per recorder callback, once per 3,200-byte chunk), so a main-thread stall queued audio without bound and delivered it in a burst. Here the conversion and send run on a private serial queue, and the main actor only publishes state into `Gate` (through `updateGate`) and receives coalesced events. The gate is read at send time, not submit time, so a pause, stop, or reconnect takes effect for every chunk that has not yet been handed to the socket.
final class SystemAudioChunkSender: @unchecked Sendable {
    /// The slice of view-model state a send decision depends on, mirrored from the main actor.
    struct Gate {
        var isRecording = false
        var isReconnectInFlight = false
        var isCapturePaused = false
        var isStreamTimingReady = false
        var transport: (any SystemAudioChunkTransport)?
    }

    /// Notifications for the main actor. Each is throttled so a failing socket or a long send burst cannot flood the main thread.
    struct Events {
        /// The gate allowed sending but no socket exists.
        var socketMissing: @Sendable () -> Void
        /// A send completed with an error.
        var sendFailed: @Sendable (_ message: String) -> Void
        /// Chunks were handed to the socket successfully since the previous report.
        var chunksSent: @Sendable (_ count: Int, _ lastChunkBytes: Int, _ sentAt: TimeInterval) -> Void
    }

    static let chunkSizeBytes = 3200
    /// 16 kHz mono Int16 is 32,000 bytes per second of audio.
    static let bytesPerSecond = 32000.0
    static let eventThrottleSeconds: TimeInterval = 1.0
    static let sentReportIntervalSeconds: TimeInterval = 0.25

    private let clock: RecordingClock
    private let markerMessage: @Sendable (TimeInterval) -> String
    private let events: Events
    private let uptime: @Sendable () -> TimeInterval
    private let queue = DispatchQueue(label: "SystemAudioChunkSender", qos: .userInitiated)
    private let stateLock = NSLock()
    private var gate = Gate()
    private var lastSocketMissingReport: TimeInterval?
    private var lastSendFailedReport: TimeInterval?
    private var lastSentReport: TimeInterval?
    private var unreportedSentCount = 0
    private var lastChunkBytes = 0

    init(
        clock: RecordingClock,
        markerMessage: @escaping @Sendable (TimeInterval) -> String,
        events: Events,
        uptime: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }
    ) {
        self.clock = clock
        self.markerMessage = markerMessage
        self.events = events
        self.uptime = uptime
    }

    /// Applies a main-actor state change to the gate. Cheap and safe to call from property observers.
    func updateGate(_ mutate: (inout Gate) -> Void) {
        stateLock.lock()
        mutate(&gate)
        stateLock.unlock()
    }

    /// The current gate values. Used by tests that verify the view model mirrors its state into the sender.
    func currentGate() -> Gate {
        stateLock.lock()
        defer { stateLock.unlock() }
        return gate
    }

    /// Accepts one buffer of native-endian Float32 mono samples at 16 kHz from a recorder's IO queue. Returns immediately; the capture-end timestamp is taken here, before any queuing delay.
    func submit(floatAudio audioData: Data) {
        let captureEndElapsed = clock.elapsedSeconds()
        queue.async { [self] in
            process(audioData, captureEndElapsed: captureEndElapsed)
        }
    }

    /// Blocks until every buffer submitted so far has been processed. Used by tests.
    func waitUntilIdle() {
        queue.sync {}
    }

    /// Clamps to [-1, 1] and guards against NaN or infinity before scaling, because `Int16(_:)` traps on out-of-range or non-finite values and CoreAudio float samples are not guaranteed to be normalized.
    static func int16Samples(fromFloat32 audioData: Data) -> Data {
        let floatData = audioData.withUnsafeBytes { $0.bindMemory(to: Float32.self) }
        guard floatData.count > 0 else { return Data() }
        var int16Data = Data(capacity: floatData.count * 2)
        for sample in floatData {
            let safeSample = sample.isFinite ? min(1.0, max(-1.0, sample)) : 0.0
            let int16Sample = Int16(safeSample * 32767.0)
            int16Data.append(contentsOf: withUnsafeBytes(of: int16Sample) { Array($0) })
        }
        return int16Data
    }

    private func process(_ audioData: Data, captureEndElapsed: TimeInterval) {
        let int16Data = Self.int16Samples(fromFloat32: audioData)
        var offset = 0
        while offset < int16Data.count {
            let length = min(Self.chunkSizeBytes, int16Data.count - offset)
            let chunk = int16Data.subdata(in: offset..<(offset + length))
            let chunkStartElapsed = max(0, captureEndElapsed - Double(int16Data.count - offset) / Self.bytesPerSecond)
            send(chunk, chunkStartElapsed: chunkStartElapsed)
            offset += length
        }
    }

    private func send(_ chunk: Data, chunkStartElapsed: TimeInterval) {
        stateLock.lock()
        let snapshot = gate
        stateLock.unlock()

        guard snapshot.isRecording,
              !snapshot.isReconnectInFlight,
              !snapshot.isCapturePaused,
              snapshot.isStreamTimingReady else { return }

        guard let transport = snapshot.transport else {
            reportSocketMissingIfDue()
            return
        }

        if clock.claimMarker(for: .systemAudio, at: chunkStartElapsed) {
            transport.sendMarker(markerMessage(chunkStartElapsed))
        }
        let chunkBytes = chunk.count
        transport.sendChunk(chunk) { [weak self] error in
            self?.handleCompletion(error, chunkBytes: chunkBytes)
        }
    }

    private func handleCompletion(_ error: Error?, chunkBytes: Int) {
        let now = uptime()
        if let error {
            stateLock.lock()
            let due = Self.isDue(lastSendFailedReport, now: now, interval: Self.eventThrottleSeconds)
            if due { lastSendFailedReport = now }
            stateLock.unlock()
            if due { events.sendFailed(error.localizedDescription) }
            return
        }

        stateLock.lock()
        unreportedSentCount += 1
        lastChunkBytes = chunkBytes
        let due = Self.isDue(lastSentReport, now: now, interval: Self.sentReportIntervalSeconds)
        var count = 0
        var bytes = 0
        if due {
            lastSentReport = now
            count = unreportedSentCount
            bytes = lastChunkBytes
            unreportedSentCount = 0
        }
        stateLock.unlock()
        if due { events.chunksSent(count, bytes, Date().timeIntervalSince1970) }
    }

    private func reportSocketMissingIfDue() {
        let now = uptime()
        stateLock.lock()
        let due = Self.isDue(lastSocketMissingReport, now: now, interval: Self.eventThrottleSeconds)
        if due { lastSocketMissingReport = now }
        stateLock.unlock()
        if due { events.socketMissing() }
    }

    private static func isDue(_ last: TimeInterval?, now: TimeInterval, interval: TimeInterval) -> Bool {
        guard let last else { return true }
        return now - last >= interval
    }
}
