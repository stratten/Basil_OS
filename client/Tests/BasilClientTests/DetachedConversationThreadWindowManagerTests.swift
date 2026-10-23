import XCTest
@testable import BasilClient

@MainActor
final class DetachedConversationThreadWindowManagerTests: XCTestCase {
    private final class Observer: ConversationDetachedThreadsObserver {
        var updates: [[String]] = []

        func updateDetachedConversationIds(_ ids: [String]) {
            updates.append(ids)
        }
    }

    func testOpenTracksConversationIdAndNotifiesObserver() {
        let manager = DetachedConversationThreadWindowManager()
        let observer = Observer()
        manager.addObserver(observer)

        XCTAssertFalse(manager.hasOpenThread(conversationId: "conversation-1"))
        XCTAssertFalse(manager.focusExistingThread(conversationId: "conversation-1"))

        manager.open(conversationId: "conversation-1")

        XCTAssertTrue(manager.hasOpenThread(conversationId: "conversation-1"))
        XCTAssertEqual(manager.detachedConversationIds, ["conversation-1"])
        XCTAssertEqual(observer.updates, [["conversation-1"]])
    }

    func testOpenNotifiesIndependentObservers() {
        let manager = DetachedConversationThreadWindowManager()
        let firstObserver = Observer()
        let secondObserver = Observer()
        manager.addObserver(firstObserver)
        manager.addObserver(secondObserver)

        manager.open(conversationId: "conversation-1")

        XCTAssertEqual(firstObserver.updates, [["conversation-1"]])
        XCTAssertEqual(secondObserver.updates, [["conversation-1"]])
    }

    func testOpeningAnAlreadyOpenConversationFocusesAndRenotifies() {
        let manager = DetachedConversationThreadWindowManager()
        let observer = Observer()
        manager.addObserver(observer)

        manager.open(conversationId: "conversation-1")
        XCTAssertEqual(observer.updates, [["conversation-1"]])

        manager.open(conversationId: "conversation-1")

        XCTAssertEqual(manager.detachedConversationIds, ["conversation-1"])
        XCTAssertEqual(observer.updates, [["conversation-1"], ["conversation-1"]])
    }

    func testRemovingObserverStopsDelivery() {
        let manager = DetachedConversationThreadWindowManager()
        let observer = Observer()
        manager.addObserver(observer)
        manager.removeObserver(observer)

        manager.open(conversationId: "conversation-1")

        XCTAssertTrue(observer.updates.isEmpty)
    }

    func testOpeningMultipleConversationsTracksAllIds() {
        let manager = DetachedConversationThreadWindowManager()
        let observer = Observer()
        manager.addObserver(observer)

        manager.open(conversationId: "conversation-1")
        manager.open(conversationId: "conversation-2")

        XCTAssertEqual(manager.detachedConversationIds, ["conversation-1", "conversation-2"])
        XCTAssertEqual(observer.updates.last, ["conversation-1", "conversation-2"])
    }

    func testOpenIgnoresEmptyConversationId() {
        let manager = DetachedConversationThreadWindowManager()
        let observer = Observer()
        manager.addObserver(observer)

        manager.open(conversationId: "")

        XCTAssertTrue(manager.detachedConversationIds.isEmpty)
        XCTAssertTrue(observer.updates.isEmpty)
    }

    func testOpenedThreadWindowReceivesLiveAppearanceUpdates() {
        let manager = DetachedConversationThreadWindowManager()
        let hostCountBeforeOpen = AppearanceRefreshCoordinator.shared.registeredHostCount

        manager.open(conversationId: "conversation-appearance")

        XCTAssertEqual(AppearanceRefreshCoordinator.shared.registeredHostCount, hostCountBeforeOpen + 1)
    }

    func testGlobalConversationWindowRefreshesAppearanceSafelyBeforeItIsShown() {
        let controller: AppearanceRefreshable = ConversationWindowController()

        controller.refreshAppearance()
    }
}
