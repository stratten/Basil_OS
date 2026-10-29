import XCTest
@testable import BasilClient

@MainActor
final class DetachedAgentTaskWindowManagerTests: XCTestCase {
    override func tearDown() {
        AgentTaskResultPresentationCoordinator.shared.resetForTesting()
        super.tearDown()
    }

    func testAddObserverReceivesBroadcastOnOpen() {
        final class RecordingObserver: AgentTaskResultDetachedRootsObserver {
            var received: [String] = []
            func updateDetachedRoots(_ ids: [String]) {
                received = ids
            }
        }

        let manager = DetachedAgentTaskWindowManager.shared
        let observer = RecordingObserver()
        manager.addObserver(observer)

        manager.open(rootTaskId: "root-1")

        XCTAssertEqual(observer.received, ["root-1"])
        manager.removeObserver(observer)
    }

    func testRemoveObserverStopsReceivingBroadcast() {
        final class RecordingObserver: AgentTaskResultDetachedRootsObserver {
            var received: [String] = []
            func updateDetachedRoots(_ ids: [String]) {
                received = ids
            }
        }

        let manager = DetachedAgentTaskWindowManager.shared
        let observer = RecordingObserver()
        manager.addObserver(observer)
        manager.removeObserver(observer)

        manager.open(rootTaskId: "root-2")

        XCTAssertEqual(observer.received, [])
    }

    func testValidationRunFocusCommandsAreNoOpsForUnknownRoots() {
        let manager = DetachedAgentTaskWindowManager.shared

        manager.requestValidationRunState(
            rootTaskId: "unknown-validation-root",
            requestId: "request-unknown"
        )
        manager.focusValidationRun(
            rootTaskId: "unknown-validation-root",
            requestId: "focus-unknown",
            runId: "validation-run-history-follow-up-2"
        )

        XCTAssertFalse(manager.detachedRootTaskIds.contains("unknown-validation-root"))
    }

    func testValidationFixtureProxiesStateAndFocusCommandsWithoutChangingObserverContract() {
        final class RecordingObserver: AgentTaskResultDetachedRootsObserver {
            var received: [[String]] = []
            func updateDetachedRoots(_ ids: [String]) {
                received.append(ids)
            }
        }

        let manager = DetachedAgentTaskWindowManager.shared
        let observer = RecordingObserver()
        manager.addObserver(observer)
        defer {
            manager.close(rootTaskId: "validation-run-history-root")
            manager.removeObserver(observer)
        }

        manager.open(rootTaskId: "validation-run-history-root")
        manager.requestValidationRunState(
            rootTaskId: "validation-run-history-root",
            requestId: "fixture-state"
        )
        manager.focusValidationRun(
            rootTaskId: "validation-run-history-root",
            requestId: "fixture-newest",
            runId: "validation-run-history-follow-up-2"
        )

        XCTAssertEqual(observer.received.last, manager.detachedRootTaskIds)
    }
}
