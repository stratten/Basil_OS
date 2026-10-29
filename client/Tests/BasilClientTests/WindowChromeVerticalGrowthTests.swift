import XCTest
@testable import BasilClient

final class WindowChromeVerticalGrowthTests: XCTestCase {
    private let visibleFrame = NSRect(x: 0, y: 0, width: 1440, height: 900)

    func testGrowsTallerWhileKeepingTheTopEdgeFixed() {
        let current = NSRect(x: 100, y: 200, width: 1180, height: 600)

        let grown = WindowChromeCollapse.verticallyGrownFrame(
            currentFrame: current,
            minimumHeight: 700,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(grown.height, 700)
        XCTAssertEqual(grown.maxY, current.maxY)
        XCTAssertEqual(grown.minX, current.minX)
        XCTAssertEqual(grown.width, current.width)
    }

    func testNeverShrinksAWindowThatIsAlreadyTallEnough() {
        let current = NSRect(x: 100, y: 50, width: 1180, height: 820)

        XCTAssertEqual(
            WindowChromeCollapse.verticallyGrownFrame(
                currentFrame: current,
                minimumHeight: 700,
                visibleFrame: visibleFrame
            ),
            current
        )
    }

    func testSlidesBackOntoTheScreenWhenGrowingWouldPushTheBottomOffScreen() {
        let current = NSRect(x: 100, y: 10, width: 1180, height: 600)

        let grown = WindowChromeCollapse.verticallyGrownFrame(
            currentFrame: current,
            minimumHeight: 780,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(grown.height, 780)
        XCTAssertGreaterThanOrEqual(grown.minY, visibleFrame.minY)
        XCTAssertLessThanOrEqual(grown.maxY, visibleFrame.maxY)
    }

    func testIsCappedAtTheVisibleScreenHeight() {
        let current = NSRect(x: 0, y: 0, width: 1180, height: 600)

        let grown = WindowChromeCollapse.verticallyGrownFrame(
            currentFrame: current,
            minimumHeight: 5000,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(grown.height, visibleFrame.height)
        XCTAssertEqual(grown.minY, visibleFrame.minY)
    }
}
