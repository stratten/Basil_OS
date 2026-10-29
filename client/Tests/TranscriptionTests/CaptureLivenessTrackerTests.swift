import XCTest
@testable import BasilClient

/// Proves the stall detector used by the microphone watchdog: a silent engine is reported from the moment it is armed, buffers reset the stall, and a disarmed tracker (paused or stopped capture) never reports a stall.
final class CaptureLivenessTrackerTests: XCTestCase {
    private var now: TimeInterval = 100

    private func makeTracker() -> CaptureLivenessTracker {
        now = 100
        return CaptureLivenessTracker(clock: { [weak self] in self?.now ?? 0 })
    }

    func testDisarmedTrackerReportsNoStall() {
        let tracker = makeTracker()
        now += 60
        XCTAssertNil(tracker.stallDuration())
    }

    func testArmedTrackerWithNoBufferCountsStallFromArming() {
        let tracker = makeTracker()
        tracker.arm()
        now += 7
        XCTAssertEqual(tracker.stallDuration() ?? -1, 7, accuracy: 0.0001)
        XCTAssertFalse(tracker.hasReceivedActivitySinceArming)
    }

    func testBufferResetsTheStall() {
        let tracker = makeTracker()
        tracker.arm()
        now += 4
        tracker.markActivity()
        now += 2
        XCTAssertEqual(tracker.stallDuration() ?? -1, 2, accuracy: 0.0001)
        XCTAssertTrue(tracker.hasReceivedActivitySinceArming)
    }

    func testRearmingForgetsPriorActivity() {
        let tracker = makeTracker()
        tracker.arm()
        tracker.markActivity()
        now += 10
        tracker.arm()
        now += 3
        XCTAssertEqual(tracker.stallDuration() ?? -1, 3, accuracy: 0.0001)
        XCTAssertFalse(tracker.hasReceivedActivitySinceArming)
    }

    func testDisarmClearsStallAndIgnoresLateBuffers() {
        let tracker = makeTracker()
        tracker.arm()
        now += 10
        tracker.disarm()
        tracker.markActivity()
        XCTAssertNil(tracker.stallDuration())
        XCTAssertFalse(tracker.hasReceivedActivitySinceArming)
    }

    func testConcurrentMarksAndReadsAreSafe() {
        let tracker = CaptureLivenessTracker()
        tracker.arm()
        let group = DispatchGroup()
        for _ in 0..<8 {
            DispatchQueue.global().async(group: group) {
                for _ in 0..<2_000 {
                    tracker.markActivity()
                    _ = tracker.stallDuration()
                }
            }
        }
        group.wait()
        XCTAssertTrue(tracker.hasReceivedActivitySinceArming)
    }
}
