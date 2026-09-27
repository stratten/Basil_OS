import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class WebKitWindowChromeAppearanceTests: XCTestCase {
    func testAppliesTransparentBorderlessWindowContract() {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 320, height: 240),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.contentView = NSView()

        WebKitWindowChromeAppearance.apply(to: window)

        XCTAssertFalse(window.hasShadow)
        XCTAssertFalse(window.isOpaque)
        XCTAssertEqual(window.backgroundColor.alphaComponent, 0)
        XCTAssertEqual(window.appearance?.name, .aqua)
        XCTAssertTrue(window.contentView?.wantsLayer == true)
        XCTAssertEqual(NSColor(cgColor: window.contentView?.layer?.backgroundColor ?? .black)?.alphaComponent, 0)
        XCTAssertEqual(window.contentView?.layer?.cornerRadius, WebKitWindowChromeAppearance.cornerRadius)
        XCTAssertFalse(window.contentView?.layer?.masksToBounds == true)
    }
}
