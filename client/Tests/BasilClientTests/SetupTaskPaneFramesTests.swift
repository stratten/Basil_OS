import XCTest
@testable import BasilClient

final class SetupTaskPaneFramesTests: XCTestCase {
    private let minimumSetupWidth: CGFloat = 988

    func testWideScreenGrowsTheWindowRightwardByThePreferredPaneWidth() throws {
        let current = NSRect(x: 100, y: 60, width: 1188, height: 848)
        let visible = NSRect(x: 0, y: 0, width: 2560, height: 1400)

        let plan = try XCTUnwrap(SetupTaskPaneFrames.openingPlan(
            currentFrame: current, minimumSetupWidth: minimumSetupWidth, visibleFrame: visible
        ))

        XCTAssertEqual(plan.paneWidth, 520)
        XCTAssertEqual(plan.windowFrame.width, 1708)
        XCTAssertEqual(plan.windowFrame.minX, 100)
        XCTAssertEqual(plan.windowFrame.minY, 60)
        XCTAssertEqual(plan.windowFrame.height, 848)
    }

    func testWindowSlidesLeftWhenGrowingWouldLeaveTheScreen() throws {
        let current = NSRect(x: 900, y: 60, width: 1188, height: 848)
        let visible = NSRect(x: 0, y: 0, width: 2560, height: 1400)

        let plan = try XCTUnwrap(SetupTaskPaneFrames.openingPlan(
            currentFrame: current, minimumSetupWidth: minimumSetupWidth, visibleFrame: visible
        ))

        XCTAssertEqual(plan.windowFrame.maxX, visible.maxX)
        XCTAssertEqual(plan.windowFrame.width, 1708)
    }

    func testNarrowScreenGivesThePaneWhatIsLeftAfterTheSetupMinimum() throws {
        let current = NSRect(x: 0, y: 0, width: 1188, height: 848)
        let visible = NSRect(x: 0, y: 0, width: 1440, height: 900)

        let plan = try XCTUnwrap(SetupTaskPaneFrames.openingPlan(
            currentFrame: current, minimumSetupWidth: minimumSetupWidth, visibleFrame: visible
        ))

        XCTAssertEqual(plan.windowFrame.width, 1440)
        XCTAssertEqual(plan.paneWidth, 452)
        XCTAssertGreaterThanOrEqual(plan.windowFrame.width - plan.paneWidth, minimumSetupWidth)
    }

    func testReturnsNilWhenEvenTheNarrowestPaneWouldSqueezeTheSetupFlow() {
        let current = NSRect(x: 0, y: 0, width: 1188, height: 700)
        let visible = NSRect(x: 0, y: 0, width: 1280, height: 800)

        XCTAssertNil(SetupTaskPaneFrames.openingPlan(
            currentFrame: current, minimumSetupWidth: minimumSetupWidth, visibleFrame: visible
        ))
    }

    func testClosingGivesBackThePaneWidthAndKeepsTheLeftEdge() {
        let current = NSRect(x: 100, y: 60, width: 1708, height: 848)

        let closed = SetupTaskPaneFrames.closingFrame(
            currentFrame: current, paneWidth: 520, minimumWindowWidth: minimumSetupWidth
        )

        XCTAssertEqual(closed, NSRect(x: 100, y: 60, width: 1188, height: 848))
    }

    func testClosingNeverShrinksBelowTheSetupMinimum() {
        let current = NSRect(x: 0, y: 0, width: 1100, height: 848)

        let closed = SetupTaskPaneFrames.closingFrame(
            currentFrame: current, paneWidth: 520, minimumWindowWidth: minimumSetupWidth
        )

        XCTAssertEqual(closed.width, minimumSetupWidth)
    }
}

@MainActor
final class AgentTaskResultEmbeddedHostLayoutTests: XCTestCase {
    func testBoardLayoutKeepsTheBoardFrameAndPresenterRole() {
        let layout = AgentTaskResultEmbeddedHost.Layout.board(topInset: 56, leadingInset: 56)

        XCTAssertEqual(layout.topInset, 56)
        XCTAssertEqual(layout.leadingInset, 56)
        XCTAssertEqual(layout.trailingInset, 8)
        XCTAssertEqual(layout.bottomInset, 8)
        XCTAssertEqual(layout.cornerRadius, 16)
        XCTAssertEqual(layout.maskedCorners, [.layerMaxXMaxYCorner])
        XCTAssertTrue(layout.sidebarInitiallyExpanded)
        XCTAssertTrue(layout.isBoardPresenter)
    }

    func testSetupPaneLayoutFillsThePaneAndIsNotTheBoardPresenter() {
        let layout = AgentTaskResultEmbeddedHost.Layout.setupPane

        XCTAssertEqual([layout.topInset, layout.leadingInset, layout.trailingInset, layout.bottomInset], [0, 0, 0, 0])
        XCTAssertFalse(layout.sidebarInitiallyExpanded)
        XCTAssertFalse(layout.isBoardPresenter)
    }
}
