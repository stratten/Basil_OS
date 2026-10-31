import XCTest
@testable import BasilClient

private final class ManualUptime: @unchecked Sendable {
    private let lock = NSLock()
    private var current: TimeInterval = 1000

    var value: TimeInterval {
        lock.lock()
        defer { lock.unlock() }
        return current
    }

    func advance(by seconds: TimeInterval) {
        lock.lock()
        current += seconds
        lock.unlock()
    }
}

/// Records every call, in order, and completes each chunk send synchronously with `chunkError`.
private final class FakeTransport: SystemAudioChunkTransport, @unchecked Sendable {
    enum Call: Equatable {
        case marker(String)
        case chunk(Int)
    }

    private let lock = NSLock()
    private var recorded: [Call] = []
    private var chunkSendHook: (() -> Void)?
    var chunkError: Error?
    let firstChunkArrived = DispatchSemaphore(value: 0)

    var calls: [Call] {
        lock.lock()
        defer { lock.unlock() }
        return recorded
    }

    func setChunkSendHook(_ hook: @escaping () -> Void) {
        lock.lock()
        chunkSendHook = hook
        lock.unlock()
    }

    func sendMarker(_ text: String) {
        lock.lock()
        recorded.append(.marker(text))
        lock.unlock()
    }

    func sendChunk(_ data: Data, completion: @escaping @Sendable (Error?) -> Void) {
        lock.lock()
        recorded.append(.chunk(data.count))
        let hook = chunkSendHook
        let error = chunkError
        lock.unlock()
        firstChunkArrived.signal()
        hook?()
        completion(error)
    }
}

private final class EventLog: @unchecked Sendable {
    private let lock = NSLock()
    private(set) var socketMissingCount = 0
    private(set) var failureMessages: [String] = []
    private(set) var sentTotal = 0
    private(set) var sentReports = 0

    func socketMissing() {
        lock.lock(); socketMissingCount += 1; lock.unlock()
    }

    func sendFailed(_ message: String) {
        lock.lock(); failureMessages.append(message); lock.unlock()
    }

    func chunksSent(_ count: Int) {
        lock.lock(); sentTotal += count; sentReports += 1; lock.unlock()
    }
}

private struct TestSendError: LocalizedError {
    var errorDescription: String? { "socket closed" }
}

final class SystemAudioChunkSenderTests: XCTestCase {
    private struct Harness {
        let sender: SystemAudioChunkSender
        let transport: FakeTransport
        let events: EventLog
        let uptime: ManualUptime
        let clockTime: ManualUptime
        let clock: RecordingClock
    }

    private func makeHarness(openGate: Bool = true, startClock: Bool = true) -> Harness {
        let clockTime = ManualUptime()
        let clock = RecordingClock(now: { clockTime.value })
        if startClock { clock.start() }
        let uptime = ManualUptime()
        let events = EventLog()
        let transport = FakeTransport()
        let sender = SystemAudioChunkSender(
            clock: clock,
            markerMessage: { "marker:\(Int($0))" },
            events: SystemAudioChunkSender.Events(
                socketMissing: { events.socketMissing() },
                sendFailed: { events.sendFailed($0) },
                chunksSent: { count, _, _ in events.chunksSent(count) }
            ),
            uptime: { uptime.value }
        )
        if openGate {
            sender.updateGate {
                $0.isRecording = true
                $0.isStreamTimingReady = true
                $0.transport = transport
            }
        }
        return Harness(sender: sender, transport: transport, events: events, uptime: uptime, clockTime: clockTime, clock: clock)
    }

    private func floatAudio(sampleCount: Int, value: Float = 0.5) -> Data {
        var samples = [Float32](repeating: value, count: sampleCount)
        return samples.withUnsafeMutableBytes { Data($0) }
    }

    private func chunkSizes(_ calls: [FakeTransport.Call]) -> [Int] {
        calls.compactMap { if case .chunk(let size) = $0 { return size } else { return nil } }
    }

    // MARK: - Conversion

    func testInt16ConversionClampsAndNeutralizesNonFiniteSamples() {
        var samples: [Float32] = [0, 1, -1, 2, -2, .nan, .infinity, -.infinity]
        let data = samples.withUnsafeMutableBytes { Data($0) }
        let converted = SystemAudioChunkSender.int16Samples(fromFloat32: data)
        let values = converted.withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
        XCTAssertEqual(values, [0, 32767, -32767, 32767, -32767, 0, 0, 0])
    }

    func testInt16ConversionOfEmptyOrTooShortInputIsEmpty() {
        XCTAssertTrue(SystemAudioChunkSender.int16Samples(fromFloat32: Data()).isEmpty)
        XCTAssertTrue(SystemAudioChunkSender.int16Samples(fromFloat32: Data([1, 2, 3])).isEmpty)
    }

    // MARK: - Chunking

    func testBufferIsSplitIntoOrderedChunksWithShortRemainder() {
        let harness = makeHarness()
        // 5,000 Float32 samples become 10,000 Int16 bytes: three full chunks and a 400-byte tail.
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(chunkSizes(harness.transport.calls), [3200, 3200, 3200, 400])
    }

    func testFirstChunkIsPrecededByClockMarkerAndLaterChunksWithinIntervalAreNot() {
        let harness = makeHarness()
        harness.clockTime.advance(by: 10)
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        let calls = harness.transport.calls
        guard case .marker = calls.first else { return XCTFail("The first call must be the clock marker, got \(calls)") }
        XCTAssertEqual(calls.filter { if case .marker = $0 { return true } else { return false } }.count, 1)
        XCTAssertEqual(chunkSizes(calls), [3200, 3200, 3200, 400])
    }

    // MARK: - Gate

    func testClosedGateConditionsEachSuppressSending() {
        let conditions: [(String, (inout SystemAudioChunkSender.Gate) -> Void)] = [
            ("not recording", { $0.isRecording = false }),
            ("reconnect in flight", { $0.isReconnectInFlight = true }),
            ("capture paused", { $0.isCapturePaused = true }),
            ("stream timing not ready", { $0.isStreamTimingReady = false })
        ]
        for (name, close) in conditions {
            let harness = makeHarness()
            harness.sender.updateGate(close)
            harness.sender.submit(floatAudio: floatAudio(sampleCount: 1600))
            harness.sender.waitUntilIdle()
            XCTAssertTrue(harness.transport.calls.isEmpty, "Nothing may be sent while \(name)")
            XCTAssertEqual(harness.events.socketMissingCount, 0, "A closed gate is not a missing socket (\(name))")
        }
    }

    func testGateIsReadAtSendTimeSoPausingMidBufferStopsRemainingChunks() {
        let harness = makeHarness()
        harness.transport.setChunkSendHook {
            harness.sender.updateGate { $0.isCapturePaused = true }
        }
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(chunkSizes(harness.transport.calls), [3200], "Only the chunk already handed to the socket may go out after the pause")
    }

    func testMissingSocketIsReportedOncePerThrottleWindow() {
        let harness = makeHarness(openGate: false)
        harness.sender.updateGate {
            $0.isRecording = true
            $0.isStreamTimingReady = true
        }
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.socketMissingCount, 1, "Four chunks inside one window report once")

        harness.uptime.advance(by: SystemAudioChunkSender.eventThrottleSeconds + 0.1)
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 1600))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.socketMissingCount, 2, "A later window reports again")
        XCTAssertTrue(harness.transport.calls.isEmpty)
    }

    // MARK: - Completion handling

    func testSendFailuresAreReportedOncePerThrottleWindowWithTheErrorText() {
        let harness = makeHarness()
        harness.transport.chunkError = TestSendError()
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.failureMessages, ["socket closed"])
        XCTAssertEqual(harness.events.sentTotal, 0, "Failed sends are not counted as sent")

        harness.uptime.advance(by: SystemAudioChunkSender.eventThrottleSeconds + 0.1)
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 1600))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.failureMessages.count, 2)
    }

    func testSuccessfulSendsAreCoalescedAndFirstReportIsImmediate() {
        let harness = makeHarness()
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 5000))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.sentReports, 1, "Four completions inside one interval produce one report")
        XCTAssertEqual(harness.events.sentTotal, 1, "The first completion reports immediately; the other three wait for the next interval")

        harness.uptime.advance(by: SystemAudioChunkSender.sentReportIntervalSeconds + 0.05)
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 1600))
        harness.sender.waitUntilIdle()
        XCTAssertEqual(harness.events.sentTotal, 5, "The next report carries the three held completions plus the new one")
    }

    // MARK: - Main-thread independence

    func testSendingDoesNotDependOnTheMainThread() {
        let harness = makeHarness()
        harness.sender.submit(floatAudio: floatAudio(sampleCount: 1600))
        // `DispatchSemaphore.wait` blocks this (main) thread without servicing the main queue, so any `DispatchQueue.main.async` in the send path would never run and this would time out.
        XCTAssertEqual(
            harness.transport.firstChunkArrived.wait(timeout: .now() + 5),
            .success,
            "The chunk must reach the socket while the main thread is blocked"
        )
    }
}
