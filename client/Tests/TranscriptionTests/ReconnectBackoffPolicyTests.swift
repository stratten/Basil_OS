import XCTest
@testable import BasilClient

final class ReconnectBackoffPolicyTests: XCTestCase {
    func testDelaySequenceUsesExponentialBackoffAndCapsAtThirtySeconds() {
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 1), 1)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 2), 2)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 3), 4)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 4), 8)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 5), 16)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 6), 30)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 12), 30)
    }

    func testNonPositiveAttemptsDoNotDelay() {
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: 0), 0)
        XCTAssertEqual(ReconnectBackoffPolicy.delaySeconds(forAttempt: -1), 0)
    }

    func testGiveUpStartsAtMaximumAttempt() {
        XCTAssertFalse(ReconnectBackoffPolicy.shouldGiveUp(afterAttempt: 5))
        XCTAssertTrue(ReconnectBackoffPolicy.shouldGiveUp(afterAttempt: 6))
        XCTAssertTrue(ReconnectBackoffPolicy.shouldGiveUp(afterAttempt: 7))
    }
}
