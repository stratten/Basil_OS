import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskFollowUpCaptureLeaseTests: XCTestCase {
    override func tearDown() {
        if let ownerID = AgentTaskFollowUpCaptureLease.shared.ownerID {
            AgentTaskFollowUpCaptureLease.shared.release(ownerID: ownerID)
        }
        super.tearDown()
    }

    func testOnlyFirstOwnerAcquiresLease() {
        let firstOwner = UUID()
        let secondOwner = UUID()

        XCTAssertTrue(
            AgentTaskFollowUpCaptureLease.shared.acquire(
                ownerID: firstOwner,
                onComplete: {},
                onCancel: {}
            )
        )
        XCTAssertFalse(
            AgentTaskFollowUpCaptureLease.shared.acquire(
                ownerID: secondOwner,
                onComplete: {},
                onCancel: {}
            )
        )
    }

    func testNonOwnerCannotReleaseLease() {
        let owner = UUID()
        let otherOwner = UUID()
        XCTAssertTrue(
            AgentTaskFollowUpCaptureLease.shared.acquire(
                ownerID: owner,
                onComplete: {},
                onCancel: {}
            )
        )

        AgentTaskFollowUpCaptureLease.shared.release(ownerID: otherOwner)

        XCTAssertEqual(AgentTaskFollowUpCaptureLease.shared.ownerID, owner)
    }
}
