import XCTest
@testable import BasilClient

/// The running-application list changes in bursts (helper apps launching and quitting), and each rebuild of the audio process list blocks on `coreaudiod`. These tests pin the contract that keeps that off the main actor: the first load is synchronous, later loads run in the background, and a burst collapses into one extra rebuild.
@available(macOS 14.0, *)
@MainActor
final class AudioProcessControllerReloadTests: XCTestCase {

    private func waitUntilIdle(_ controller: AudioProcessController, timeout: TimeInterval = 20) async {
        let deadline = Date().addingTimeInterval(timeout)
        while controller.isReloadInFlight && Date() < deadline {
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
    }

    func testTheFirstDeliveryIsBuiltSynchronouslyAndStartsNoBackgroundWork() {
        let controller = AudioProcessController()

        controller.handleRunningApplicationsChange([])

        XCTAssertTrue(controller.hasLoadedProcesses)
        XCTAssertFalse(controller.isReloadInFlight)
        XCTAssertEqual(controller.backgroundReloadCount, 0)
    }

    func testALaterDeliveryRunsInTheBackgroundAndFinishesIdle() async {
        let controller = AudioProcessController()
        controller.handleRunningApplicationsChange([])

        controller.handleRunningApplicationsChange([])

        XCTAssertTrue(controller.isReloadInFlight, "A later delivery must not be built inline on the main actor")
        XCTAssertEqual(controller.backgroundReloadCount, 1)
        await waitUntilIdle(controller)
        XCTAssertFalse(controller.isReloadInFlight)
        XCTAssertEqual(controller.pendingNotificationCount, 0)
    }

    func testABurstWhileARebuildRunsCollapsesIntoOneMoreRebuild() async {
        let controller = AudioProcessController()
        controller.handleRunningApplicationsChange([])
        controller.handleRunningApplicationsChange([])

        // Rebuilds can only finish on the main actor, so these four arrive while the first is still in flight.
        for _ in 0..<4 { controller.handleRunningApplicationsChange([]) }

        XCTAssertEqual(controller.backgroundReloadCount, 1)
        XCTAssertEqual(controller.pendingNotificationCount, 4)
        await waitUntilIdle(controller)
        XCTAssertFalse(controller.isReloadInFlight)
        XCTAssertEqual(controller.backgroundReloadCount, 2, "Five notifications after the first load must cost two rebuilds, not five")
        XCTAssertEqual(controller.pendingNotificationCount, 0)
    }

    func testANotificationAfterTheControllerSettlesStartsAFreshRebuild() async {
        let controller = AudioProcessController()
        controller.handleRunningApplicationsChange([])
        controller.handleRunningApplicationsChange([])
        await waitUntilIdle(controller)

        controller.handleRunningApplicationsChange([])

        XCTAssertTrue(controller.isReloadInFlight)
        XCTAssertEqual(controller.backgroundReloadCount, 2)
        await waitUntilIdle(controller)
        XCTAssertFalse(controller.isReloadInFlight)
    }
}
