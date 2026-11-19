import AppKit
import XCTest
@preconcurrency import WebKit
@testable import BasilClient

@MainActor
final class WindowDragAreaViewTests: XCTestCase {
    func testAgentTaskStopAndBubbleRegionsPassThrough() {
        let dragArea = WindowDragAreaView()
        dragArea.frame = NSRect(x: 0, y: 0, width: 400, height: 44)

        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 263, y: 22)) === dragArea)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 264, y: 22)))
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 280, y: 22)))
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 320, y: 22)))
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 380, y: 22)))
    }

    func testBoardHeaderControlsPassThrough() {
        let dragArea = WindowDragAreaView(leadingInteractiveWidth: 84, trailingInteractiveWidth: 76)
        dragArea.frame = NSRect(x: 0, y: 0, width: 400, height: 44)

        XCTAssertNil(dragArea.hitTest(NSPoint(x: 83, y: 22)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 84, y: 22)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 323, y: 22)) === dragArea)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 324, y: 22)))
    }

    func testConversationConfigurationLeavesTheTrailingHeaderDraggable() {
        let dragArea = WindowDragAreaView(leadingInteractiveWidth: 109, trailingInteractiveWidth: 0)
        dragArea.frame = NSRect(x: 0, y: 0, width: 400, height: 44)

        XCTAssertNil(dragArea.hitTest(NSPoint(x: 108, y: 22)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 109, y: 22)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 399, y: 22)) === dragArea)
    }

    func testMeetingAssistantHeaderControlsPassThrough() {
        let dragArea = WindowDragAreaView(leadingInteractiveWidth: 90, trailingInteractiveWidth: 76)
        dragArea.frame = NSRect(x: 0, y: 0, width: 400, height: 56)

        XCTAssertNil(dragArea.hitTest(NSPoint(x: 89, y: 28)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 90, y: 28)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 323, y: 28)) === dragArea)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 324, y: 28)))
    }

    func testReportedRangesReplaceTheFixedWidthsSoTheRightOfACollapsedWidgetDrags() {
        let dragArea = WindowDragAreaView()
        dragArea.frame = NSRect(x: 0, y: 0, width: 300, height: 78)
        dragArea.interactiveRanges = [0..<114]

        XCTAssertNil(dragArea.hitTest(NSPoint(x: 113, y: 40)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 114, y: 40)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 164, y: 40)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 250, y: 40)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 299, y: 40)) === dragArea)
    }

    func testReportedRangesProtectOnlyThePauseAndStopButtonsBesideTheBubble() {
        let dragArea = WindowDragAreaView()
        dragArea.frame = NSRect(x: 0, y: 0, width: 300, height: 78)
        dragArea.interactiveRanges = [0..<114, 190..<248]

        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 189, y: 40)) === dragArea)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 190, y: 40)))
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 247, y: 40)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 248, y: 40)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 280, y: 40)) === dragArea)
    }

    func testBeforeAnyReportTheFixedWidthsStillApply() {
        let dragArea = WindowDragAreaView()
        dragArea.frame = NSRect(x: 0, y: 0, width: 300, height: 78)

        XCTAssertNil(dragArea.interactiveRanges)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 119, y: 40)))
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 200, y: 40)))
    }

    func testAgentTaskResultHostAppliesReportedGeometryAndDropsMalformedRanges() throws {
        let host = AgentTaskResultWebView()
        host.installDragArea()
        host.webView.frame = NSRect(x: 0, y: 0, width: 300, height: 78)

        host.updateDragAreaGeometry(
            height: 78,
            interactiveRanges: [(start: 0, end: 114), (start: 200, end: 200), (start: 250, end: 240), (start: -5, end: 30), (start: 190, end: 248)]
        )

        let dragArea = try XCTUnwrap(host.dragAreaView)
        XCTAssertEqual(dragArea.interactiveRanges, [0..<114, 190..<248])
    }

    func testSetupInstallerCoversHeaderAndPreservesWindowControls() throws {
        let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 400, height: 200))

        SetupWindowDragAreaInstaller.install(in: webView)
        webView.layoutSubtreeIfNeeded()

        let dragArea = try XCTUnwrap(webView.subviews.compactMap { $0 as? WindowDragAreaView }.first)
        XCTAssertEqual(
            dragArea.frame.height,
            WebKitWindowChromeAppearance.frameInset + SetupWindowDragAreaInstaller.headerHeight
        )
        XCTAssertEqual(dragArea.frame.width, webView.bounds.width)
        XCTAssertNil(dragArea.hitTest(NSPoint(x: 83, y: 22)))
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 84, y: 22)) === dragArea)
        XCTAssertTrue(dragArea.hitTest(NSPoint(x: 399, y: 22)) === dragArea)
    }
}
