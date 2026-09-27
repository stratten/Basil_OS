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
}
