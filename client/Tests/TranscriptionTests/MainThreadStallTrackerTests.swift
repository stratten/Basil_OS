import XCTest
@testable import BasilClient

/// Proves the detection rules of the main-thread stall watchdog without needing a real freeze: a heartbeat is posted when none is outstanding, a prompt answer reports nothing, an unanswered heartbeat is reported once at the threshold, and the eventual answer reports the recovery.
final class MainThreadStallTrackerTests: XCTestCase {
    private func makeTracker() -> MainThreadStallTracker {
        MainThreadStallTracker(thresholdSeconds: 2)
    }

    func testFirstTickPostsAHeartbeatAndReportsNothing() {
        var tracker = makeTracker()
        let result = tracker.tick(now: 10)
        XCTAssertTrue(result.sendPing)
        XCTAssertNil(result.event)
    }

    func testOutstandingHeartbeatIsNotReplacedByAnotherPing() {
        var tracker = makeTracker()
        _ = tracker.tick(now: 10)
        let result = tracker.tick(now: 10.5)
        XCTAssertFalse(result.sendPing)
        XCTAssertNil(result.event)
    }

    func testPromptAnswerReportsNoStallAndAllowsTheNextPing() {
        var tracker = makeTracker()
        _ = tracker.tick(now: 10)
        XCTAssertNil(tracker.acknowledge(now: 10.01))
        XCTAssertTrue(tracker.tick(now: 10.5).sendPing)
    }

    func testUnansweredHeartbeatIsReportedOnceAtTheThreshold() {
        var tracker = makeTracker()
        _ = tracker.tick(now: 10)
        XCTAssertNil(tracker.tick(now: 11.9).event)
        XCTAssertEqual(tracker.tick(now: 12.0).event, .stalled(ageSeconds: 2))
        XCTAssertNil(tracker.tick(now: 12.5).event)
        XCTAssertNil(tracker.tick(now: 40).event)
    }

    func testAnswerAfterAStallReportsTheRecoveryFromWhenTheHeartbeatWasPosted() {
        var tracker = makeTracker()
        _ = tracker.tick(now: 10)
        _ = tracker.tick(now: 12.0)
        let recovered = tracker.acknowledge(now: 47)
        guard case .recovered(let duration)? = recovered else {
            return XCTFail("Expected a recovery event, got \(String(describing: recovered))")
        }
        XCTAssertEqual(duration, 37, accuracy: 0.0001)
    }

    func testAfterRecoveryTheNextStallIsReportedAgain() {
        var tracker = makeTracker()
        _ = tracker.tick(now: 10)
        _ = tracker.tick(now: 12)
        _ = tracker.acknowledge(now: 20)
        XCTAssertTrue(tracker.tick(now: 20.5).sendPing)
        XCTAssertEqual(tracker.tick(now: 22.5).event, .stalled(ageSeconds: 2))
    }

    func testAnswerWithNoOutstandingHeartbeatIsIgnored() {
        var tracker = makeTracker()
        XCTAssertNil(tracker.acknowledge(now: 5))
    }
}
