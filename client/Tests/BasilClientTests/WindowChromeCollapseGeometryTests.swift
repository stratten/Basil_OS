import XCTest
@testable import BasilClient

final class WindowChromeCollapseGeometryTests: XCTestCase {
    private let visibleFrame = NSRect(x: 0, y: 0, width: 1440, height: 900)
    private let expandedFrame = NSRect(x: 300, y: 300, width: 560, height: 420)
    private let initialCompactFrame = NSRect(x: 300, y: 656, width: 300, height: 64)

    func testUnmovedCompactFrameRestoresExactExpandedFrame() {
        XCTAssertEqual(
            WindowChromeCollapse.expandedFrame(
                savedFrame: expandedFrame,
                initialCompactFrame: initialCompactFrame,
                currentCompactFrame: initialCompactFrame,
                visibleFrame: visibleFrame
            ),
            expandedFrame
        )
    }

    func testCollapseAnchorRetainsTopLeftForAFrameNearestTheLeftEdge() {
        let frame = NSRect(x: 24, y: 300, width: 560, height: 420)

        XCTAssertEqual(
            WindowChromeCollapse.collapseAnchor(frame: frame, visibleFrame: visibleFrame),
            .topLeft
        )
    }

    func testCollapseAnchorRetainsTopRightForAFrameNearestTheRightEdge() {
        let frame = NSRect(x: 856, y: 300, width: 560, height: 420)

        XCTAssertEqual(
            WindowChromeCollapse.collapseAnchor(frame: frame, visibleFrame: visibleFrame),
            .topRight
        )
    }

    func testCollapseAnchorPreservesExistingLeftBehaviorWhenEquidistant() {
        let frame = NSRect(x: 440, y: 300, width: 560, height: 420)

        XCTAssertEqual(
            WindowChromeCollapse.collapseAnchor(frame: frame, visibleFrame: visibleFrame),
            .topLeft
        )
    }

    func testTopRightCompactFrameExpandsDownAndLeft() {
        let compact = NSRect(x: 1120, y: 820, width: 300, height: 64)

        let result = WindowChromeCollapse.expandedFrame(
            savedFrame: expandedFrame,
            initialCompactFrame: initialCompactFrame,
            currentCompactFrame: compact,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.maxX, compact.maxX)
        XCTAssertEqual(result.maxY, compact.maxY)
        XCTAssertEqual(result.size, expandedFrame.size)
    }

    func testTopLeftCompactFrameExpandsDownAndRight() {
        let compact = NSRect(x: 20, y: 816, width: 300, height: 64)

        let result = WindowChromeCollapse.expandedFrame(
            savedFrame: expandedFrame,
            initialCompactFrame: initialCompactFrame,
            currentCompactFrame: compact,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.minX, compact.minX)
        XCTAssertEqual(result.maxY, compact.maxY)
        XCTAssertEqual(result.size, expandedFrame.size)
    }

    func testBottomLeftCompactFrameExpandsUpAndRight() {
        let compact = NSRect(x: 20, y: 20, width: 300, height: 64)

        let result = WindowChromeCollapse.expandedFrame(
            savedFrame: expandedFrame,
            initialCompactFrame: initialCompactFrame,
            currentCompactFrame: compact,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.minX, compact.minX)
        XCTAssertEqual(result.minY, compact.minY)
        XCTAssertEqual(result.size, expandedFrame.size)
    }

    func testBottomRightCompactFrameExpandsUpAndLeft() {
        let compact = NSRect(x: 1120, y: 20, width: 300, height: 64)

        let result = WindowChromeCollapse.expandedFrame(
            savedFrame: expandedFrame,
            initialCompactFrame: initialCompactFrame,
            currentCompactFrame: compact,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.maxX, compact.maxX)
        XCTAssertEqual(result.minY, compact.minY)
        XCTAssertEqual(result.size, expandedFrame.size)
    }

    func testOversizedSavedFrameIsConstrainedToVisibleFrame() {
        let oversized = NSRect(x: 10, y: 10, width: 2000, height: 1200)
        let movedCompact = NSRect(x: 1120, y: 820, width: 300, height: 64)

        let result = WindowChromeCollapse.expandedFrame(
            savedFrame: oversized,
            initialCompactFrame: initialCompactFrame,
            currentCompactFrame: movedCompact,
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result, visibleFrame)
        XCTAssertEqual(oversized.size, NSSize(width: 2000, height: 1200))
    }

    func testLayoutResizeFrameClampsOversizedHeightInsideVisibleFrame() {
        let result = WindowChromeCollapse.layoutResizeFrame(
            currentFrame: NSRect(x: 180, y: 360, width: 500, height: 300),
            requestedSize: NSSize(width: 500, height: 1200),
            minSize: NSSize(width: 400, height: 300),
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.height, visibleFrame.height)
        XCTAssertTrue(visibleFrame.contains(result))
    }

    func testLayoutResizeFrameRetainsTopEdgeWhenExpansionFits() {
        let currentFrame = NSRect(x: 180, y: 320, width: 500, height: 300)
        let result = WindowChromeCollapse.layoutResizeFrame(
            currentFrame: currentFrame,
            requestedSize: NSSize(width: 700, height: 480),
            minSize: NSSize(width: 400, height: 300),
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(result.maxY, currentFrame.maxY)
        XCTAssertEqual(result.size, NSSize(width: 700, height: 480))
    }

    func testCenteredFrameFitsOversizedInitialSetupWindowInsideSmallDisplay() {
        let smallVisibleFrame = NSRect(x: 50, y: 100, width: 900, height: 620)
        let result = WindowChromeCollapse.centeredFrame(
            requestedSize: NSSize(width: 1_220, height: 824),
            minSize: NSSize(width: 1_020, height: 684),
            visibleFrame: smallVisibleFrame
        )

        XCTAssertEqual(result, smallVisibleFrame)
    }

    func testMovedCompactFrameSelectsItsCurrentScreen() {
        let leftScreen = NSRect(x: 0, y: 0, width: 1440, height: 900)
        let rightScreen = NSRect(x: 1440, y: 0, width: 1440, height: 900)
        let movedCompact = NSRect(x: 1800, y: 700, width: 300, height: 64)

        let result = WindowChromeCollapse.resolvedVisibleFrame(
            currentScreenVisibleFrame: leftScreen,
            frame: movedCompact,
            screenVisibleFrames: [leftScreen, rightScreen],
            fallbackVisibleFrame: leftScreen
        )

        XCTAssertEqual(result, rightScreen)
    }

    func testScreenSelectionUsesGreatestIntersectionWhenCenterIsBetweenScreens() {
        let leftScreen = NSRect(x: 0, y: 0, width: 1000, height: 800)
        let rightScreen = NSRect(x: 1000, y: 0, width: 1000, height: 800)
        let spanningCompact = NSRect(x: 900, y: 600, width: 300, height: 64)

        let result = WindowChromeCollapse.resolvedVisibleFrame(
            currentScreenVisibleFrame: nil,
            frame: spanningCompact,
            screenVisibleFrames: [leftScreen, rightScreen],
            fallbackVisibleFrame: leftScreen
        )

        XCTAssertEqual(result, rightScreen)
    }

    @MainActor
    func testCollapseAndExpandRestoreWindowConstraints() {
        let window = NSWindow(
            contentRect: expandedFrame,
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        let originalMinSize = NSSize(width: 400, height: 300)
        let originalMaxSize = NSSize(width: 1200, height: 900)
        window.minSize = originalMinSize
        window.maxSize = originalMaxSize
        window.contentMinSize = originalMinSize
        window.contentMaxSize = originalMaxSize
        var state: WindowChromeCollapse.State?

        WindowChromeCollapse.collapse(
            window: window,
            preferredCompactSize: NSSize(width: 300, height: 64),
            state: &state
        )

        XCTAssertEqual(window.frame.size, NSSize(width: 300, height: 64))
        XCTAssertEqual(window.minSize, NSSize(width: 300, height: 64))
        XCTAssertEqual(window.maxSize, NSSize(width: 300, height: 64))
        XCTAssertNotNil(state)

        WindowChromeCollapse.expand(
            window: window,
            state: &state,
            fallbackSize: NSSize(width: 500, height: 400)
        )

        XCTAssertEqual(window.minSize, originalMinSize)
        XCTAssertEqual(window.maxSize, originalMaxSize)
        XCTAssertEqual(window.contentMinSize, originalMinSize)
        XCTAssertEqual(window.contentMaxSize, originalMaxSize)
        XCTAssertNil(state)
    }

    @MainActor
    func testCollapseHonorsRequested280PointHeaderWidthBelowSharedCap() {
        let window = NSWindow(
            contentRect: NSRect(x: 300, y: 300, width: 800, height: 600),
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        var state: WindowChromeCollapse.State?

        WindowChromeCollapse.collapse(
            window: window,
            preferredCompactSize: NSSize(width: 280, height: 64),
            state: &state
        )

        XCTAssertEqual(window.frame.size, NSSize(width: 280, height: 64))
        XCTAssertEqual(window.minSize, NSSize(width: 280, height: 64))
        XCTAssertEqual(window.maxSize, NSSize(width: 280, height: 64))
    }

    @MainActor
    func testContentResizeDoesNotShrinkBelowCurrentFrame() {
        let window = NSWindow(
            contentRect: NSRect(x: 300, y: 300, width: 900, height: 600),
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        window.minSize = NSSize(width: 400, height: 300)

        WindowChromeCollapse.applyContentResize(
            window: window,
            requestedSize: NSSize(width: 668, height: 420)
        )

        XCTAssertEqual(window.frame.size, NSSize(width: 900, height: 600))
    }

    @MainActor
    func testContentResizeGrowsWhenRequestedSizeIsLarger() {
        let window = NSWindow(
            contentRect: NSRect(x: 300, y: 300, width: 560, height: 420),
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        window.minSize = NSSize(width: 400, height: 300)

        WindowChromeCollapse.applyContentResize(
            window: window,
            requestedSize: NSSize(width: 988, height: 500)
        )

        XCTAssertEqual(window.frame.size, NSSize(width: 988, height: 500))
    }

    func testLayoutResizeCanShrinkAndRetainsTopLeftEdge() {
        let originalFrame = NSRect(x: 300, y: 300, width: 900, height: 600)
        let resizedFrame = WindowChromeCollapse.layoutResizeFrame(
            currentFrame: originalFrame,
            requestedSize: NSSize(width: 604, height: 400),
            minSize: NSSize(width: 444, height: 300),
            visibleFrame: visibleFrame
        )

        XCTAssertEqual(resizedFrame.size, NSSize(width: 604, height: 400))
        XCTAssertEqual(NSPoint(x: resizedFrame.minX, y: resizedFrame.maxY), NSPoint(x: originalFrame.minX, y: originalFrame.maxY))
    }

    @MainActor
    func testLayoutResizeClampsToDynamicMinimum() {
        let window = NSWindow(
            contentRect: NSRect(x: 300, y: 300, width: 900, height: 600),
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        window.minSize = NSSize(width: 636, height: 300)

        WindowChromeCollapse.applyLayoutResize(
            window: window,
            requestedSize: NSSize(width: 444, height: 240)
        )

        XCTAssertEqual(window.frame.size, NSSize(width: 636, height: 300))
    }

    @MainActor
    func testRepeatedCollapseRetainsOriginalExpandedFrame() {
        let window = NSWindow(
            contentRect: expandedFrame,
            styleMask: [.borderless, .resizable],
            backing: .buffered,
            defer: false
        )
        var state: WindowChromeCollapse.State?

        WindowChromeCollapse.collapse(
            window: window,
            preferredCompactSize: NSSize(width: 300, height: 64),
            state: &state
        )
        let savedFrame = state?.expandedFrame

        WindowChromeCollapse.collapse(
            window: window,
            preferredCompactSize: NSSize(width: 280, height: 64),
            state: &state
        )

        XCTAssertEqual(state?.expandedFrame, savedFrame)
        XCTAssertEqual(state?.expandedFrame, expandedFrame)
    }
}
