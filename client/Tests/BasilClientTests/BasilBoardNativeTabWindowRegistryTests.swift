import XCTest
@testable import BasilClient

@MainActor
final class BasilBoardNativeTabWindowRegistryTests: XCTestCase {
    func testRegisteredTabInvokesItsNativeOpener() {
        var opened = false

        XCTAssertTrue(BasilBoardNativeTabWindowRegistry.open(
            tabId: "agent_tasks",
            openers: ["agent_tasks": { opened = true }]
        ))
        XCTAssertTrue(opened)
    }

    func testUnknownTabIsRejectedWithoutOpeningAnything() {
        var opened = false

        XCTAssertFalse(BasilBoardNativeTabWindowRegistry.open(
            tabId: "unknown",
            openers: ["agent_tasks": { opened = true }]
        ))
        XCTAssertFalse(opened)
    }
}
