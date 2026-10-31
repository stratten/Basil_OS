import Foundation

/// Pure state machine behind ``MainThreadStallWatchdog``: it is told when a heartbeat was posted to the main thread and when the main thread answered, and it reports when an unanswered heartbeat has aged past the threshold and when the answer finally arrives. It owns no clock or queue, so a test can drive it with explicit times.
struct MainThreadStallTracker {
    enum Event: Equatable {
        /// A heartbeat posted to the main thread is still unanswered after ``thresholdSeconds``; `ageSeconds` is how long it has waited.
        case stalled(ageSeconds: Double)
        /// The main thread answered a heartbeat that had been reported as stalled; `durationSeconds` runs from when that heartbeat was posted, so it is a lower bound on the stall.
        case recovered(durationSeconds: Double)
    }

    let thresholdSeconds: Double
    private(set) var pingSentAt: Double?
    private(set) var stallReported = false

    init(thresholdSeconds: Double) {
        self.thresholdSeconds = thresholdSeconds
    }

    /// Call on every watchdog tick. `sendPing` is true when no heartbeat is outstanding and the caller must post one to the main thread now.
    mutating func tick(now: Double) -> (sendPing: Bool, event: Event?) {
        guard let sent = pingSentAt else {
            pingSentAt = now
            return (true, nil)
        }
        let age = now - sent
        if !stallReported && age >= thresholdSeconds {
            stallReported = true
            return (false, .stalled(ageSeconds: age))
        }
        return (false, nil)
    }

    /// Call when the main thread runs the outstanding heartbeat. Returns ``Event/recovered(durationSeconds:)`` only when that heartbeat had been reported as stalled.
    mutating func acknowledge(now: Double) -> Event? {
        guard let sent = pingSentAt else { return nil }
        let wasStalled = stallReported
        pingSentAt = nil
        stallReported = false
        return wasStalled ? .recovered(durationSeconds: now - sent) : nil
    }
}

#if DEBUG
/// Detects main-thread stalls and records what the app was doing. A background timer posts a heartbeat to the main thread every half second; when one goes unanswered for two seconds the watchdog writes a line to `BasilDebugLogs/Basil_MainStalls_<date>.log` and asks `/usr/bin/sample` for a three-second stack sample of this process, so the next freeze names the code that blocked the main thread. Everything here runs off the main thread, because the ordinary desktop log is written through the main actor and goes silent during exactly the stalls this exists to explain. The file is only written while desktop logging is enabled, and samples are capped per launch and spaced apart.
final class MainThreadStallWatchdog: @unchecked Sendable {
    static let shared = MainThreadStallWatchdog()

    static let tickSeconds = 0.5
    static let thresholdSeconds = 2.0
    static let maxSamplesPerLaunch = 6
    static let minSecondsBetweenSamples = 60.0
    static let sampleDurationSeconds = 3

    private let queue = DispatchQueue(label: "com.basil.main-thread-stall-watchdog", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var tracker = MainThreadStallTracker(thresholdSeconds: MainThreadStallWatchdog.thresholdSeconds)
    private var samplesTaken = 0
    private var lastSampleAt: Double?

    private init() {}

    /// Starts the watchdog; calling it again is harmless.
    func start() {
        queue.async { [self] in
            guard timer == nil else { return }
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + Self.tickSeconds, repeating: Self.tickSeconds, leeway: .milliseconds(100))
            source.setEventHandler { [weak self] in self?.handleTick() }
            timer = source
            source.resume()
        }
    }

    private static func monotonicSeconds() -> Double {
        Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000_000
    }

    private func handleTick() {
        let result = tracker.tick(now: Self.monotonicSeconds())
        if result.sendPing {
            DispatchQueue.main.async { [weak self] in
                let answeredAt = Self.monotonicSeconds()
                self?.queue.async { self?.handleAnswer(at: answeredAt) }
            }
        }
        if let event = result.event {
            handle(event)
        }
    }

    private func handleAnswer(at time: Double) {
        if let event = tracker.acknowledge(now: time) {
            handle(event)
        }
    }

    private func handle(_ event: MainThreadStallTracker.Event) {
        switch event {
        case .stalled(let age):
            record("Main thread has not responded for \(String(format: "%.1f", age))s; sampling the process")
            sampleProcessIfAllowed()
        case .recovered(let duration):
            record("Main thread responded again after a stall of at least \(String(format: "%.1f", duration))s")
        }
    }

    private func record(_ message: String) {
        DevLogger.shared.warning(message, context: "MainThreadStallWatchdog")
        guard let directory = Self.stallLogDirectory() else { return }
        let line = "[\(Self.timestamp(format: "yyyy-MM-dd HH:mm:ss.SSS"))] \(message)\n"
        let file = directory.appendingPathComponent("Basil_MainStalls_\(Self.timestamp(format: "yyyyMMdd")).log")
        if !FileManager.default.fileExists(atPath: file.path) {
            FileManager.default.createFile(atPath: file.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: file), let data = line.data(using: .utf8) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    }

    private func sampleProcessIfAllowed() {
        let now = Self.monotonicSeconds()
        guard samplesTaken < Self.maxSamplesPerLaunch else { return }
        if let last = lastSampleAt, now - last < Self.minSecondsBetweenSamples { return }
        guard let directory = Self.stallLogDirectory() else { return }
        let output = directory.appendingPathComponent("Basil_MainStall_\(Self.timestamp(format: "yyyyMMdd_HHmmss")).sample.txt")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/sample")
        process.arguments = [String(ProcessInfo.processInfo.processIdentifier), String(Self.sampleDurationSeconds), "10", "-file", output.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            samplesTaken += 1
            lastSampleAt = now
        } catch {
            DevLogger.shared.warning("Could not start /usr/bin/sample: \(error.localizedDescription)", context: "MainThreadStallWatchdog")
        }
    }

    /// The shared debug-log folder, or nil when desktop logging is off, so nothing is written for a user who has not opted in.
    private static func stallLogDirectory() -> URL? {
        guard BasilRuntimeProfile.userDefaults.bool(forKey: "DesktopLoggingEnabled"),
              let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first else { return nil }
        let directory = desktop.appendingPathComponent("BasilDebugLogs", isDirectory: true)
        guard (try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)) != nil else { return nil }
        return directory
    }

    private static func timestamp(format: String) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = format
        return formatter.string(from: Date())
    }
}
#else
/// Release builds carry no watchdog: it samples the process and writes to the desktop, which only debug builds do.
final class MainThreadStallWatchdog: @unchecked Sendable {
    static let shared = MainThreadStallWatchdog()
    private init() {}
    func start() {}
}
#endif
