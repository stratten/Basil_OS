import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskOriginNavigatorTests: XCTestCase {
    func testRejectsBlankOriginIdentifier() {
        XCTAssertFalse(
            AgentTaskOriginNavigator.open(
                originType: "todo",
                originId: "",
                originatingWindow: nil
            )
        )
    }

    func testRejectsUnregisteredOriginType() {
        XCTAssertFalse(
            AgentTaskOriginNavigator.open(
                originType: "validation_fixture",
                originId: "fixture-1",
                originatingWindow: nil
            )
        )
    }
}
