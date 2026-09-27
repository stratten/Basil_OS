import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskResultPresentationCoordinatorTests: XCTestCase {
    override func tearDown() {
        AgentTaskResultPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testNoPresenterIsActiveByDefault() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        XCTAssertNil(coordinator.activePresenter)
    }

    func testStandaloneBecomingVisibleWinsArbitration() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.standaloneDidBecomeVisible()
        XCTAssertEqual(coordinator.activePresenter, .standalone)
    }

    func testBoardWinsWhenStandaloneIsNotVisible() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.registerBoardVisible()
        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testStandaloneWinsOverBoardWhenBothVisible() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()
        XCTAssertEqual(coordinator.activePresenter, .standalone)
    }

    func testStandaloneDismissFallsBackToBoardWhenBoardIsVisible() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.registerBoardVisible()
        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidDismiss()
        XCTAssertEqual(coordinator.activePresenter, .board)
    }

    func testStandaloneDismissIsIdempotentWhenAlreadyHidden() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.standaloneDidDismiss()
        coordinator.standaloneDidDismiss()
        XCTAssertNil(coordinator.activePresenter)
    }

    func testUnregisterBoardVisibleClearsBoardOwnership() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.registerBoardVisible()
        coordinator.unregisterBoardVisible()
        XCTAssertNil(coordinator.activePresenter)
    }

    func testAddObserverIsNotifiedOnEveryStateChange() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        var notifications = 0
        let observerId = UUID()
        coordinator.addObserver(id: observerId) { notifications += 1 }

        coordinator.standaloneDidBecomeVisible()
        coordinator.standaloneDidDismiss()
        coordinator.registerBoardVisible()
        coordinator.unregisterBoardVisible()

        XCTAssertEqual(notifications, 4)
        coordinator.removeObserver(id: observerId)
    }

    func testRemovedObserverIsNotNotified() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        var notifications = 0
        let observerId = UUID()
        coordinator.addObserver(id: observerId) { notifications += 1 }
        coordinator.removeObserver(id: observerId)

        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(notifications, 0)
    }

    func testAddObserverWithSameIdReplacesThePreviousClosure() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        var firstCallCount = 0
        var secondCallCount = 0
        let observerId = UUID()
        coordinator.addObserver(id: observerId) { firstCallCount += 1 }
        coordinator.addObserver(id: observerId) { secondCallCount += 1 }

        coordinator.registerBoardVisible()

        XCTAssertEqual(firstCallCount, 0)
        XCTAssertEqual(secondCallCount, 1)
        coordinator.removeObserver(id: observerId)
    }

    func testUpdateBoardFocusedRowIsReadableViaAuthoritativeFocusedRowStateWhenBoardIsAuthoritative() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.registerBoardVisible()
        coordinator.updateBoardFocusedRow(
            agentTaskId: "task-1",
            isProcessing: false,
            hasResult: true,
            supportsFollowUp: true
        )

        let focused = coordinator.authoritativeFocusedRowState
        XCTAssertEqual(focused?.agentTaskId, "task-1")
        XCTAssertTrue(focused?.supportsFollowUp ?? false)
    }

    func testAuthoritativeFocusedRowStateReturnsStandaloneStateWhenStandaloneVisible() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        let widget = AgentTaskResultWidgetController.ensureShared()
        widget.updateFocusedRow(
            agentTaskId: "standalone-task",
            isProcessing: true,
            hasResult: false,
            supportsFollowUp: false
        )
        coordinator.registerBoardVisible()
        coordinator.updateBoardFocusedRow(
            agentTaskId: "board-task",
            isProcessing: false,
            hasResult: true,
            supportsFollowUp: true
        )
        coordinator.standaloneDidBecomeVisible()

        XCTAssertEqual(coordinator.authoritativeFocusedRowState?.agentTaskId, "standalone-task")
        widget.dismiss()
    }

    func testAuthoritativeFocusedRowStateIsNilWhenNeitherSurfaceVisible() {
        let coordinator = AgentTaskResultPresentationCoordinator.shared
        coordinator.updateBoardFocusedRow(
            agentTaskId: "orphan-task",
            isProcessing: false,
            hasResult: true,
            supportsFollowUp: true
        )

        XCTAssertNil(coordinator.authoritativeFocusedRowState)
    }
}
