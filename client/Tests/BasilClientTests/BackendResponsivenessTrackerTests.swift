import XCTest
@testable import BasilClient

/// Proves when the native monitor offers to restart a frozen backend: never during start-up, never for a backend that keeps answering between failures, once per streak after the offer threshold, again only after the re-offer interval, and never twice for a single outage.
final class BackendResponsivenessTrackerTests: XCTestCase {
    private func makeTracker() -> BackendResponsivenessTracker {
        BackendResponsivenessTracker(offerAfterSeconds: 60, reofferAfterSeconds: 300)
    }

    private func makeHealthyTracker() -> BackendResponsivenessTracker {
        var tracker = makeTracker()
        _ = tracker.record(isHealthy: true, now: 0)
        return tracker
    }

    func testFailuresBeforeTheBackendHasEverAnsweredNeverOffer() {
        var tracker = makeTracker()
        for second in stride(from: 0.0, through: 600.0, by: 5.0) {
            XCTAssertNil(tracker.record(isHealthy: false, now: second))
        }
    }

    func testAHealthyBackendNeverOffers() {
        var tracker = makeTracker()
        for second in stride(from: 0.0, through: 600.0, by: 5.0) {
            XCTAssertNil(tracker.record(isHealthy: true, now: second))
        }
    }

    func testOffersOnceWhenEveryProbeHasFailedForTheThreshold() {
        var tracker = makeHealthyTracker()
        XCTAssertNil(tracker.record(isHealthy: false, now: 10))
        XCTAssertNil(tracker.record(isHealthy: false, now: 69.9))
        XCTAssertEqual(tracker.record(isHealthy: false, now: 70), .offerRestart(unresponsiveSeconds: 60))
        XCTAssertNil(tracker.record(isHealthy: false, now: 75))
        XCTAssertNil(tracker.record(isHealthy: false, now: 200))
    }

    func testOneSuccessfulProbeClearsTheStreak() {
        var tracker = makeHealthyTracker()
        XCTAssertNil(tracker.record(isHealthy: false, now: 10))
        XCTAssertNil(tracker.record(isHealthy: false, now: 65))
        XCTAssertNil(tracker.record(isHealthy: true, now: 66))
        XCTAssertNil(tracker.record(isHealthy: false, now: 70))
        XCTAssertNil(tracker.record(isHealthy: false, now: 129))
        XCTAssertEqual(tracker.record(isHealthy: false, now: 130), .offerRestart(unresponsiveSeconds: 60))
    }

    func testReoffersOnlyAfterTheReofferIntervalWhileStillUnresponsive() {
        var tracker = makeHealthyTracker()
        _ = tracker.record(isHealthy: false, now: 10)
        XCTAssertEqual(tracker.record(isHealthy: false, now: 70), .offerRestart(unresponsiveSeconds: 60))
        XCTAssertNil(tracker.record(isHealthy: false, now: 369))
        XCTAssertEqual(tracker.record(isHealthy: false, now: 370), .offerRestart(unresponsiveSeconds: 360))
    }

    func testAnswerAfterAnOfferReportsRecoveryOnceAndStartsAFreshStreak() {
        var tracker = makeHealthyTracker()
        _ = tracker.record(isHealthy: false, now: 10)
        _ = tracker.record(isHealthy: false, now: 70)
        XCTAssertEqual(tracker.record(isHealthy: true, now: 80), .recoveredAfterOffer)
        XCTAssertNil(tracker.record(isHealthy: true, now: 85))
        XCTAssertNil(tracker.record(isHealthy: false, now: 90))
        XCTAssertNil(tracker.record(isHealthy: false, now: 149))
        XCTAssertEqual(tracker.record(isHealthy: false, now: 150), .offerRestart(unresponsiveSeconds: 60))
    }

    func testClearStreakAfterARestartKeepsStartupGraceOnlyUntilTheNextFullStreak() {
        var tracker = makeHealthyTracker()
        _ = tracker.record(isHealthy: false, now: 10)
        _ = tracker.record(isHealthy: false, now: 70)
        tracker.clearStreak()
        XCTAssertNil(tracker.record(isHealthy: false, now: 100))
        XCTAssertNil(tracker.record(isHealthy: false, now: 159))
        XCTAssertEqual(tracker.record(isHealthy: false, now: 160), .offerRestart(unresponsiveSeconds: 60))
    }

    func testClearStreakDoesNotReportRecoveryForTheClearedOffer() {
        var tracker = makeHealthyTracker()
        _ = tracker.record(isHealthy: false, now: 10)
        _ = tracker.record(isHealthy: false, now: 70)
        tracker.clearStreak()
        XCTAssertNil(tracker.record(isHealthy: true, now: 80))
    }
}
