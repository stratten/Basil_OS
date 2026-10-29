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
