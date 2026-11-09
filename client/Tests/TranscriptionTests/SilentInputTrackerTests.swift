import XCTest
@testable import BasilClient

/// Proves the silent-microphone detector: exact zeros start a silence clock, any signal stops it, a disarmed or re-armed tracker forgets the past, and the policy retries a few times before warning and then retries slowly.
final class SilentInputTrackerTests: XCTestCase {
    private var now: TimeInterval = 100

    private func makeTracker() -> SilentInputTracker {
        now = 100
        return SilentInputTracker(clock: { [weak self] in self?.now ?? 0 })
    }

    func testDisarmedTrackerReportsNoSilence() {
        let tracker = makeTracker()
        tracker.markBuffer(isSilent: true)
        now += 60
        XCTAssertNil(tracker.silenceDuration())
    }

    func testArmedTrackerWithNoBufferIsNotSilentYet() {
        let tracker = makeTracker()
        tracker.arm()
        now += 30
        XCTAssertNil(tracker.silenceDuration())
        XCTAssertFalse(tracker.hasHeardSignalSinceArming)
    }

    func testSilenceIsCountedFromTheFirstSilentBuffer() {
        let tracker = makeTracker()
        tracker.arm()
        now += 5
        tracker.markBuffer(isSilent: true)
        now += 3
        tracker.markBuffer(isSilent: true)
        now += 2
        XCTAssertEqual(tracker.silenceDuration() ?? -1, 5, accuracy: 0.0001)
    }

    func testSignalEndsTheSilenceAndIsRemembered() {
        let tracker = makeTracker()
        tracker.arm()
        tracker.markBuffer(isSilent: true)
        now += 9
        tracker.markBuffer(isSilent: false)
        XCTAssertNil(tracker.silenceDuration())
        XCTAssertTrue(tracker.hasHeardSignalSinceArming)
    }

    func testSilenceAfterSignalStartsAFreshClock() {
        let tracker = makeTracker()
        tracker.arm()
        tracker.markBuffer(isSilent: false)
        now += 20
        tracker.markBuffer(isSilent: true)
        now += 4
        XCTAssertEqual(tracker.silenceDuration() ?? -1, 4, accuracy: 0.0001)
    }

    func testRearmingForgetsSilenceAndSignal() {
        let tracker = makeTracker()
        tracker.arm()
        tracker.markBuffer(isSilent: false)
        tracker.markBuffer(isSilent: true)
        now += 10
        tracker.arm()
        XCTAssertNil(tracker.silenceDuration())
        XCTAssertFalse(tracker.hasHeardSignalSinceArming)
    }

    func testDisarmClearsSilenceAndIgnoresLateBuffers() {
        let tracker = makeTracker()
        tracker.arm()
        tracker.markBuffer(isSilent: true)
        now += 10
        tracker.disarm()
        tracker.markBuffer(isSilent: true)
        XCTAssertNil(tracker.silenceDuration())
        XCTAssertFalse(tracker.hasHeardSignalSinceArming)
    }

    func testDigitalSilenceDetectionNeedsEveryExactZero() {
        let zeros = [Int16](repeating: 0, count: 1_600)
        var oneLeastSignificantBit = zeros
        oneLeastSignificantBit[1_599] = 1
        let empty = [Int16]()

        zeros.withUnsafeBufferPointer { XCTAssertTrue(SilentInputTracker.isDigitalSilence($0)) }
        oneLeastSignificantBit.withUnsafeBufferPointer { XCTAssertFalse(SilentInputTracker.isDigitalSilence($0)) }
        empty.withUnsafeBufferPointer { XCTAssertFalse(SilentInputTracker.isDigitalSilence($0)) }
    }

    func testConcurrentMarksAndReadsAreSafe() {
        let tracker = SilentInputTracker()
        tracker.arm()
        let group = DispatchGroup()
        for worker in 0..<8 {
            DispatchQueue.global().async(group: group) {
                for index in 0..<2_000 {
                    tracker.markBuffer(isSilent: (index + worker) % 3 != 0)
                    _ = tracker.silenceDuration()
                }
            }
        }
        group.wait()
        XCTAssertTrue(tracker.hasHeardSignalSinceArming)
    }

    func testPolicyDoesNothingUntilSilenceLastsLongEnough() {
        let policy = SilentInputPolicy()
        XCTAssertEqual(policy.action(silentFor: nil, attempts: 0), .none)
        XCTAssertEqual(policy.action(silentFor: 7.9, attempts: 0), .none)
        XCTAssertEqual(policy.action(silentFor: 8, attempts: 0), .reclaim)
    }

    func testPolicyRetriesAtTheShortIntervalBeforeTheWarning() {
        let policy = SilentInputPolicy()
        XCTAssertEqual(policy.action(silentFor: 8, attempts: 1), .reclaim)
        XCTAssertEqual(policy.action(silentFor: 8, attempts: 2), .reclaim)
    }

    func testPolicyRetriesSlowlyOnceTheWarningThresholdIsReached() {
        let policy = SilentInputPolicy()
        XCTAssertEqual(policy.action(silentFor: 29.9, attempts: 3), .none)
        XCTAssertEqual(policy.action(silentFor: 30, attempts: 3), .reclaim)
        XCTAssertEqual(policy.action(silentFor: 30, attempts: 9), .reclaim)
    }

    func testPolicyWarnsOnlyAfterEnoughFailedAttemptsAndFreshSilence() {
        let policy = SilentInputPolicy()
        XCTAssertFalse(policy.shouldWarn(silentFor: 60, attempts: 2))
        XCTAssertFalse(policy.shouldWarn(silentFor: nil, attempts: 3))
        XCTAssertFalse(policy.shouldWarn(silentFor: 2, attempts: 3))
        XCTAssertTrue(policy.shouldWarn(silentFor: 8, attempts: 3))
        XCTAssertTrue(policy.shouldWarn(silentFor: 45, attempts: 7))
    }
}
