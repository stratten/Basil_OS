import XCTest
@testable import BasilClient

final class SetupAgentTaskRevisionPolicyTests: XCTestCase {
    private let continuationNote = "Only three all-day events came back.\n\nBasil is continuing automatically to close this gap: Retry reading the recurring meetings, read-only."

    private func item(_ status: String, _ message: String? = nil) -> SetupAgentTaskRevisionPolicy.ChainItem {
        SetupAgentTaskRevisionPolicy.ChainItem(status: status, resultMessage: message)
    }

    func testAPlainFinishedTaskIsSettledImmediately() {
        let decision = SetupAgentTaskRevisionPolicy.decide(
            rootStatus: "completed", rootResultMessage: "Done.", chain: [], secondsSinceRootSettled: 0
        )
        XCTAssertEqual(decision, .settled(status: "completed", resultMessage: "Done."))
    }

    func testAnAnnouncedContinuationThatHasNotAppearedYetIsWaitedFor() {
        let decision = SetupAgentTaskRevisionPolicy.decide(
            rootStatus: "completed", rootResultMessage: continuationNote, chain: [], secondsSinceRootSettled: 5
        )
        XCTAssertEqual(decision, .revising)
    }

    func testAContinuationThatNeverAppearsIsAcceptedAsFinalAfterTheGracePeriod() {
        let decision = SetupAgentTaskRevisionPolicy.decide(
            rootStatus: "completed",
            rootResultMessage: continuationNote,
            chain: [],
            secondsSinceRootSettled: SetupAgentTaskRevisionPolicy.announcementGraceSeconds + 1
        )
        XCTAssertEqual(decision, .settled(status: "completed", resultMessage: continuationNote))
    }

    func testARunningRevisionKeepsTheTaskOpen() {
        for status in ["running", "processing", "routing", "scheduled"] {
            let decision = SetupAgentTaskRevisionPolicy.decide(
                rootStatus: "completed", rootResultMessage: continuationNote, chain: [item(status)], secondsSinceRootSettled: 500
            )
            XCTAssertEqual(decision, .revising, status)
        }
    }

    func testAFinishedRevisionSettlesWithTheRevisedResult() {
        let decision = SetupAgentTaskRevisionPolicy.decide(
            rootStatus: "completed",
            rootResultMessage: continuationNote,
            chain: [item("completed", "No conflicts this week; two back-to-back meetings on Tuesday.")],
            secondsSinceRootSettled: 40
        )
        XCTAssertEqual(
            decision,
            .settled(status: "completed", resultMessage: "No conflicts this week; two back-to-back meetings on Tuesday.")
        )
    }

    func testAFailedRevisionSettlesAsFailed() {
        let decision = SetupAgentTaskRevisionPolicy.decide(
            rootStatus: "completed", rootResultMessage: continuationNote, chain: [item("failed", "Calendar was closed.")], secondsSinceRootSettled: 40
        )
        XCTAssertEqual(decision, .settled(status: "failed", resultMessage: "Calendar was closed."))
    }

    func testTheGapIsReadFromTheBackendNote() {
        XCTAssertEqual(
            SetupAgentTaskRevisionPolicy.gapBeingClosed(in: continuationNote),
            "Retry reading the recurring meetings, read-only."
        )
        XCTAssertNil(SetupAgentTaskRevisionPolicy.gapBeingClosed(in: "Done."))
        XCTAssertNil(SetupAgentTaskRevisionPolicy.gapBeingClosed(in: nil))
        XCTAssertNil(SetupAgentTaskRevisionPolicy.gapBeingClosed(in: "Basil is continuing automatically to close this gap:   "))
    }

    func testTheAnnouncementNamesTheGapWhenKnown() {
        let withGap = SetupAgentTaskRevisionPolicy.revisionAnnouncement(rootResultMessage: continuationNote)
        XCTAssertTrue(withGap.contains("revising its work on its own"))
        XCTAssertTrue(withGap.contains("Retry reading the recurring meetings"))
        XCTAssertFalse(SetupAgentTaskRevisionPolicy.revisionAnnouncement(rootResultMessage: nil).contains("Gap it is working on"))
    }
}
