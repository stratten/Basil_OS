import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class WebViewWindowPresentationHelpersTests: XCTestCase {
    func testAppliesClearLayerBackedContentView() {
        let panel = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 320, height: 240),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentView = NSView()

        applyWebViewWindowAppearance(for: panel)

        XCTAssertTrue(panel.contentView?.wantsLayer == true)
        XCTAssertEqual(NSColor(cgColor: panel.contentView?.layer?.backgroundColor ?? .black)?.alphaComponent, 0)
    }

    func testReadyGateDeliversOnlyOnce() {
        let gate = WebViewReadyGate()
        var readyDeliveries = 0

        gate.deliverReady { readyDeliveries += 1 }
        gate.deliverReady { readyDeliveries += 1 }

        XCTAssertEqual(readyDeliveries, 1)
    }
}
