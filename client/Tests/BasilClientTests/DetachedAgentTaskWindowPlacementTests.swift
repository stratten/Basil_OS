import XCTest
@testable import BasilClient

final class DetachedAgentTaskWindowPlacementTests: XCTestCase {
    private let leftScreen = NSRect(x: 0, y: 0, width: 1440, height: 900)
    private let rightScreen = NSRect(x: 1440, y: 0, width: 1440, height: 900)
    private let windowSize = NSSize(width: 560, height: 400)

    func testOriginatingScreenTakesPrecedenceOverSourceFrame() {
        let sourceFrame = NSRect(x: 300, y: 300, width: 560, height: 400)

        let result = DetachedAgentTaskWindowPlacement.resolvedVisibleFrame(
            originatingScreenVisibleFrame: rightScreen,
            sourceFrame: sourceFrame,
            screenVisibleFrames: [leftScreen, rightScreen],
            fallbackVisibleFrame: leftScreen
        )

        XCTAssertEqual(result, rightScreen)
    }

    func testFrameIsClampedInsideVisibleFrame() {
        let visibleFrame = NSRect(x: 0, y: 0, width: 480, height: 320)
        let sourceFrame = NSRect(x: 400, y: 250, width: 560, height: 400)

        let result = DetachedAgentTaskWindowPlacement.frame(
            windowSize: windowSize,
            sourceFrame: sourceFrame,
            visibleFrame: visibleFrame,
            occupiedFrames: []
        )

        XCTAssertEqual(result, visibleFrame)
    }

    func testChoosesAFreeCandidateWhenPrimaryCandidateIsOccupied() {
        let sourceFrame = NSRect(x: 120, y: 300, width: 560, height: 400)
        let primaryCandidate = NSRect(x: 704, y: 300, width: 560, height: 400)

        let result = DetachedAgentTaskWindowPlacement.frame(
            windowSize: windowSize,
            sourceFrame: sourceFrame,
            visibleFrame: leftScreen,
            occupiedFrames: [primaryCandidate]
        )

        XCTAssertFalse(result.intersects(primaryCandidate))
        XCTAssertTrue(leftScreen.contains(result))
    }

    func testSaturatedScreenFallsBackToLowestOverlapCandidate() {
        let sourceFrame = NSRect(x: 100, y: 250, width: 560, height: 400)
        let occupiedFrame = leftScreen

        let result = DetachedAgentTaskWindowPlacement.frame(
            windowSize: windowSize,
            sourceFrame: sourceFrame,
            visibleFrame: leftScreen,
            occupiedFrames: [occupiedFrame]
        )

        XCTAssertTrue(leftScreen.contains(result))
        XCTAssertEqual(result.size, windowSize)
    }
}
