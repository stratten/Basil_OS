import XCTest
@testable import BasilClient

@MainActor
final class DetachedBasilBoardTabWindowManagerTests: XCTestCase {
    func testOpenOrFocusRejectsNonBoardWindowTabId() {
        let manager = DetachedBasilBoardTabWindowManager()
        var changedCallCount = 0
        manager.onDetachedTabsChanged = { _ in changedCallCount += 1 }

        manager.openOrFocus(tabId: "home")
        manager.openOrFocus(tabId: "agent_tasks")
        manager.openOrFocus(tabId: "chats")

        XCTAssertTrue(manager.detachedTabIds.isEmpty)
        XCTAssertEqual(changedCallCount, 0)
    }

    func testOpenOrFocusTracksBoardWindowTabId() {
        let manager = DetachedBasilBoardTabWindowManager()
        var lastChangedIds: [String] = []
        manager.onDetachedTabsChanged = { ids in lastChangedIds = ids }

        manager.openOrFocus(tabId: "meetings")

        XCTAssertEqual(manager.detachedTabIds, ["meetings"])
        XCTAssertEqual(lastChangedIds, ["meetings"])

        manager.closeAll()
        XCTAssertTrue(manager.detachedTabIds.isEmpty)
        XCTAssertEqual(lastChangedIds, [])
    }
}
