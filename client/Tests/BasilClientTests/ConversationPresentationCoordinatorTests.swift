import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class ConversationPresentationCoordinatorTests: XCTestCase {
    override func tearDown() {
        ConversationPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testNoPresenterIsActiveByDefault() {
        XCTAssertNil(ConversationPresentationCoordinator.shared.activePresenter)
    }

    func testBoardOwnsPresentationWhenItIsTheOnlyVisibleSurface() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.registerBoardVisible()

        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testStandaloneOwnsPresentationWhenItIsTheOnlyVisibleSurface() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(coordinator.activePresenter, .standalone)
    }

    func testStandaloneWinsWhenBothSurfacesAreVisible() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(coordinator.activePresenter, .standalone)
    }

    func testHidingStandaloneReturnsAuthorityToVisibleBoard() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidDismiss()

        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testMiniaturizingStandaloneReturnsAuthorityToVisibleBoard() {
        let coordinator = ConversationPresentationCoordinator.shared
        let windowController = ConversationWindowController()

        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()
        windowController.windowDidMiniaturize(Notification(name: NSWindow.didMiniaturizeNotification))

        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testDeminiaturizingStandaloneRestoresAuthority() {
        let coordinator = ConversationPresentationCoordinator.shared
        let windowController = ConversationWindowController()

        coordinator.registerBoardVisible()
        windowController.windowDidDeminiaturize(Notification(name: NSWindow.didDeminiaturizeNotification))

        XCTAssertEqual(coordinator.activePresenter, .standalone)
    }

    func testNativeWindowCloseClearsStandaloneAuthority() {
        let coordinator = ConversationPresentationCoordinator.shared
        let windowController = ConversationWindowController()

        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()
        windowController.windowWillClose(Notification(name: NSWindow.willCloseNotification))

        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testRepeatedStandaloneDismissIsIdempotent() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.standaloneDidDismiss()
        coordinator.standaloneDidDismiss()

        XCTAssertNil(coordinator.activePresenter)
    }

    func testUnregisteringBoardClearsItsAuthority() {
        let coordinator = ConversationPresentationCoordinator.shared

        coordinator.registerBoardVisible()
        coordinator.unregisterBoardVisible()

        XCTAssertNil(coordinator.activePresenter)
    }

    func testObserverReceivesEveryVisibilityTransition() {
        let coordinator = ConversationPresentationCoordinator.shared
        let observerID = UUID()
        var notifications = 0

        coordinator.addObserver(id: observerID) {
            notifications += 1
        }
        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidDismiss()
        coordinator.registerBoardVisible()
        coordinator.unregisterBoardVisible()

        XCTAssertEqual(notifications, 4)
    }

    func testRepeatedVisibilityReportsDoNotNotifyObservers() {
        let coordinator = ConversationPresentationCoordinator.shared
        let observerID = UUID()
        var notifications = 0

        coordinator.addObserver(id: observerID) {
            notifications += 1
        }
        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidDismiss()
        coordinator.standaloneDidDismiss()

        XCTAssertEqual(notifications, 2)
    }

    func testRegisteringObserverWithSameIdentifierReplacesPriorClosure() {
        let coordinator = ConversationPresentationCoordinator.shared
        let observerID = UUID()
        var firstNotifications = 0
        var secondNotifications = 0

        coordinator.addObserver(id: observerID) {
            firstNotifications += 1
        }
        coordinator.addObserver(id: observerID) {
            secondNotifications += 1
        }
        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(firstNotifications, 0)
        XCTAssertEqual(secondNotifications, 1)
    }

    func testRemovedObserverIsNotNotified() {
        let coordinator = ConversationPresentationCoordinator.shared
        let observerID = UUID()
        var notifications = 0

        coordinator.addObserver(id: observerID) {
            notifications += 1
        }
        coordinator.removeObserver(id: observerID)
        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(notifications, 0)
    }

}
