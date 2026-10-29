import XCTest
@testable import BasilClient

final class LiveTranscriptionLayoutPolicyTests: XCTestCase {
    func testCompactSizeRemainsIndependentOfExpandedSidebarFloor() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.compactSize,
            NSSize(width: 300, height: 70)
        )
    }

    func testCollapsedSidebarUsesNarrowExpandedFloor() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: true),
            NSSize(width: 480, height: 606)
        )
    }

    func testExpandedSidebarUsesFullLayoutFloor() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: false),
            NSSize(width: 826, height: 606)
        )
    }

    func testCollapsedSidebarClampsWidthOnlyUnderflow() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.constrainedExpandedSize(
                NSSize(width: 1, height: 700),
                sidebarCollapsed: true
            ),
            NSSize(width: 480, height: 700)
        )
    }

    func testExpandedSidebarClampsWidthAndHeightUnderflow() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.constrainedExpandedSize(
                NSSize(width: 1, height: 1),
                sidebarCollapsed: false
            ),
            NSSize(width: 826, height: 606)
        )
    }

    func testExpandedSizePreservesLargerDimensions() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.constrainedExpandedSize(
                NSSize(width: 900, height: 700),
                sidebarCollapsed: false
            ),
            NSSize(width: 900, height: 700)
        )
    }

    func testCompanionExtentRaisesTheWidthFloorOnly() {
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.panelMinimumSize(sidebarCollapsed: false, companionExtent: 340),
            NSSize(width: 1166, height: 606)
        )
        XCTAssertEqual(
            LiveTranscriptionLayoutPolicy.constrainedExpandedSize(NSSize(width: 900, height: 700), sidebarCollapsed: false, companionExtent: 340),
            NSSize(width: 1166, height: 700)
        )
    }

    func testCompanionGrowthExtendsTheRightEdgeAndKeepsTheLeftEdge() {
        let result = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: NSRect(x: 100, y: 50, width: 860, height: 640),
            delta: 340,
            visibleFrame: NSRect(x: 0, y: 0, width: 1920, height: 1080),
            minimumWidth: 826
        )
        XCTAssertEqual(result.frame, NSRect(x: 100, y: 50, width: 1200, height: 640))
        XCTAssertEqual(result.achievedDelta, 340)
    }

    func testCompanionGrowthSlidesLeftOnlyAsFarAsTheScreenEdgeRequires() {
        let result = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: NSRect(x: 900, y: 50, width: 860, height: 640),
            delta: 340,
            visibleFrame: NSRect(x: 0, y: 0, width: 1920, height: 1080),
            minimumWidth: 826
        )
        XCTAssertEqual(result.frame, NSRect(x: 720, y: 50, width: 1200, height: 640))
        XCTAssertEqual(result.achievedDelta, 340)
    }

    func testCompanionGrowthIsCappedAtTheVisibleWidth() {
        let result = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: NSRect(x: 0, y: 0, width: 860, height: 640),
            delta: 340,
            visibleFrame: NSRect(x: 0, y: 0, width: 1000, height: 800),
            minimumWidth: 826
        )
        XCTAssertEqual(result.frame, NSRect(x: 0, y: 0, width: 1000, height: 640))
        XCTAssertEqual(result.achievedDelta, 140)
    }

    func testCompanionShrinkKeepsTheLeftEdgeAndStopsAtTheFloor() {
        let visible = NSRect(x: 0, y: 0, width: 1920, height: 1080)
        let shrunk = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: NSRect(x: 720, y: 50, width: 1200, height: 640),
            delta: -340,
            visibleFrame: visible,
            minimumWidth: 826
        )
        XCTAssertEqual(shrunk.frame, NSRect(x: 720, y: 50, width: 860, height: 640))
        XCTAssertEqual(shrunk.achievedDelta, -340)

        let floored = LiveTranscriptionLayoutPolicy.companionResizedFrame(
            frame: NSRect(x: 0, y: 0, width: 900, height: 640),
            delta: -340,
            visibleFrame: visible,
            minimumWidth: 826
        )
        XCTAssertEqual(floored.frame.width, 826)
        XCTAssertEqual(floored.achievedDelta, -74)
    }
}
