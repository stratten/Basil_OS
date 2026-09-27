import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskFollowUpFocusRegistryTests: XCTestCase {
    func testFocusedEligibleOwnerStartsItsFollowUp() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let owner = UUID()
        var startedTaskId: String?
        registry.register(ownerID: owner) { startedTaskId = $0 }
        registry.update(
            ownerID: owner,
            agentTaskId: "root-task",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.focus(ownerID: owner)

        XCTAssertTrue(registry.startFocusedFollowUp())
        XCTAssertEqual(startedTaskId, "root-task")
        registry.unregister(ownerID: owner)
    }

    func testProcessingOwnerCannotStartFollowUp() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let owner = UUID()
        registry.register(ownerID: owner) { _ in XCTFail("Must not start") }
        registry.update(
            ownerID: owner,
            agentTaskId: "root-task",
            isProcessing: true,
            supportsFollowUp: true
        )
        registry.focus(ownerID: owner)

        XCTAssertFalse(registry.startFocusedFollowUp())
        registry.unregister(ownerID: owner)
    }

    func testKeyWindowOwnerWinsOverEligiblePrimaryOwner() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let primaryOwner = UUID()
        let detachedOwner = UUID()
        var startedOwner: UUID?

        registry.register(ownerID: primaryOwner) { _ in startedOwner = primaryOwner }
        registry.register(ownerID: detachedOwner) { _ in startedOwner = detachedOwner }
        registry.update(
            ownerID: primaryOwner,
            agentTaskId: "primary-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.update(
            ownerID: detachedOwner,
            agentTaskId: "detached-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: primaryOwner)
        registry.focus(ownerID: detachedOwner)

        XCTAssertTrue(registry.startFocusedFollowUp())
        XCTAssertEqual(startedOwner, detachedOwner)

        registry.unregister(ownerID: detachedOwner)
        registry.unregister(ownerID: primaryOwner)
    }

    func testPrimaryOwnerStartsFollowUpWhenNoWindowIsKey() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let primaryOwner = UUID()
        var startedTaskId: String?

        registry.register(ownerID: primaryOwner) { startedTaskId = $0 }
        registry.update(
            ownerID: primaryOwner,
            agentTaskId: "primary-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: primaryOwner)

        XCTAssertTrue(registry.startFocusedFollowUp())
        XCTAssertEqual(startedTaskId, "primary-root")

        registry.unregister(ownerID: primaryOwner)
    }

    func testDetachedOwnerDoesNotStartFollowUpWhenNotKeyAndNoPrimaryExists() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let detachedOwner = UUID()
        registry.register(ownerID: detachedOwner) { _ in XCTFail("Must not start") }
        registry.update(
            ownerID: detachedOwner,
            agentTaskId: "detached-root",
            isProcessing: false,
            supportsFollowUp: true
        )

        XCTAssertFalse(registry.startFocusedFollowUp())

        registry.unregister(ownerID: detachedOwner)
    }

    func testProcessingKeyWindowBlocksEligiblePrimaryFallback() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let primaryOwner = UUID()
        let processingDetachedOwner = UUID()
        registry.register(ownerID: primaryOwner) { _ in XCTFail("Primary must not start") }
        registry.register(ownerID: processingDetachedOwner) { _ in XCTFail("Processing detached window must not start") }
        registry.update(
            ownerID: primaryOwner,
            agentTaskId: "primary-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.update(
            ownerID: processingDetachedOwner,
            agentTaskId: "detached-root",
            isProcessing: true,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: primaryOwner)
        registry.focus(ownerID: processingDetachedOwner)

        XCTAssertFalse(registry.startFocusedFollowUp())

        registry.unregister(ownerID: processingDetachedOwner)
        registry.unregister(ownerID: primaryOwner)
    }

    func testResignedKeyWindowFallsBackToPrimaryOwner() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let primaryOwner = UUID()
        let detachedOwner = UUID()
        var startedOwner: UUID?

        registry.register(ownerID: primaryOwner) { _ in startedOwner = primaryOwner }
        registry.register(ownerID: detachedOwner) { _ in startedOwner = detachedOwner }
        registry.update(
            ownerID: primaryOwner,
            agentTaskId: "primary-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.update(
            ownerID: detachedOwner,
            agentTaskId: "detached-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: primaryOwner)
        registry.focus(ownerID: detachedOwner)
        registry.resignFocus(ownerID: detachedOwner)

        XCTAssertTrue(registry.startFocusedFollowUp())
        XCTAssertEqual(startedOwner, primaryOwner)

        registry.unregister(ownerID: detachedOwner)
        registry.unregister(ownerID: primaryOwner)
    }

    func testClearedPrimaryOwnerCannotStartFollowUpWithoutKeyWindow() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let primaryOwner = UUID()
        registry.register(ownerID: primaryOwner) { _ in XCTFail("Must not start") }
        registry.update(
            ownerID: primaryOwner,
            agentTaskId: "primary-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: primaryOwner)
        registry.clearPrimary(ownerID: primaryOwner)

        XCTAssertFalse(registry.startFocusedFollowUp())

        registry.unregister(ownerID: primaryOwner)
    }

    func testPrimaryOwnerStartsFollowUpAfterFocusedStatusUpdate() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let owner = UUID()
        var startedTaskId: String?
        registry.register(ownerID: owner) { startedTaskId = $0 }
        registry.setPrimary(ownerID: owner)
        registry.update(
            ownerID: owner,
            agentTaskId: "board-root",
            isProcessing: false,
            supportsFollowUp: true
        )

        XCTAssertTrue(registry.startFocusedFollowUp())
        XCTAssertEqual(startedTaskId, "board-root")
        registry.unregister(ownerID: owner)
    }

    func testUnregisteredPrimaryOwnerCannotStartFollowUp() {
        let registry = AgentTaskFollowUpFocusRegistry.shared
        let owner = UUID()
        registry.register(ownerID: owner) { _ in XCTFail("Must not start") }
        registry.update(
            ownerID: owner,
            agentTaskId: "board-root",
            isProcessing: false,
            supportsFollowUp: true
        )
        registry.setPrimary(ownerID: owner)
        registry.unregister(ownerID: owner)

        XCTAssertFalse(registry.startFocusedFollowUp())
    }
}
