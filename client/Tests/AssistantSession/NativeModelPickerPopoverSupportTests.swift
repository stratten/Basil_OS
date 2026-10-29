import AppKit
import SwiftUI
import WebKit
import XCTest
@testable import BasilClient

final class NativeModelPickerPopoverSupportTests: XCTestCase {
    private let hostBounds = NSRect(x: 0, y: 0, width: 320, height: 200)

    func testFlippedHostKeepsWebRectUnchanged() {
        let rect = NativeModelPickerPopoverSupport.anchorRect(
            webX: 290, webY: 178, width: 14, height: 14,
            hostBounds: hostBounds, hostIsFlipped: true
        )
        XCTAssertEqual(rect, NSRect(x: 290, y: 178, width: 14, height: 14))
    }

    func testUnflippedHostMirrorsWebRectVertically() {
        let rect = NativeModelPickerPopoverSupport.anchorRect(
            webX: 290, webY: 178, width: 14, height: 14,
            hostBounds: hostBounds, hostIsFlipped: false
        )
        XCTAssertEqual(rect, NSRect(x: 290, y: 8, width: 14, height: 14))
    }

    @MainActor
    func testWKWebViewReportsFlippedCoordinates() {
        let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 10, height: 10))
        XCTAssertTrue(webView.isFlipped)
    }

    func testAppearanceFollowsColorScheme() {
        XCTAssertEqual(NativeModelPickerPopoverSupport.appearanceName(for: .dark), .darkAqua)
        XCTAssertEqual(NativeModelPickerPopoverSupport.appearanceName(for: .light), .aqua)
    }

    @MainActor
    func testPaintIsNoOpWhenPopoverHasNotBeenShown() {
        let popover = NSPopover()
        popover.contentViewController = NSViewController()
        popover.contentViewController?.view = NSView(frame: NSRect(x: 0, y: 0, width: 10, height: 10))
        NativeModelPickerPopoverSupport.paintFrameBackground(of: popover, color: .black)
        XCTAssertNil(popover.contentViewController?.view.superview)
    }
}
