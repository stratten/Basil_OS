import XCTest
@testable import BasilClient

@MainActor
final class WindowCollapseControllerTests: XCTestCase {
    private func makeWindow(frame: NSRect) -> NSWindow {
        let window = NSWindow(
            contentRect: frame,
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.setFrame(frame, display: false)
        return window
    }

    func testCollapseShrinksToClampedCompactSize() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 700, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 700, height: 600)
        )

        controller.setCollapsed(true, animated: false)

        XCTAssertTrue(controller.isCollapsed)
        XCTAssertEqual(window.frame.width, 300, accuracy: 0.5)
        XCTAssertEqual(window.frame.height, 64, accuracy: 0.5)
    }

    func testCollapseClampsWidthToNarrowerWindow() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 250, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 700, height: 600)
        )

        controller.setCollapsed(true, animated: false)

        XCTAssertEqual(window.frame.width, 250, accuracy: 0.5)
    }

    func testExpandRestoresPriorExpandedFrame() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 700, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 500, height: 400)
        )

        controller.setCollapsed(true, animated: false)
        controller.setCollapsed(false, animated: false)

        XCTAssertFalse(controller.isCollapsed)
        XCTAssertEqual(window.frame.width, 700, accuracy: 0.5)
        XCTAssertEqual(window.frame.height, 600, accuracy: 0.5)
    }

    func testToggleFlipsCollapsedState() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 700, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 700, height: 600)
        )

        controller.toggle()
        XCTAssertTrue(controller.isCollapsed)
        controller.toggle()
        XCTAssertFalse(controller.isCollapsed)
    }

    func testCollapsePreferredCompactSizeOverridesConstructorDefault() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 700, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 700, height: 600)
        )

        controller.setCollapsed(true, preferredCompactSize: NSSize(width: 220, height: 90), animated: false)

        XCTAssertTrue(controller.isCollapsed)
        XCTAssertEqual(window.frame.width, 220, accuracy: 0.5)
        XCTAssertEqual(window.frame.height, 90, accuracy: 0.5)
    }

    func testExpandFallbackExpandedSizeOverridesConstructorDefault() {
        let window = makeWindow(frame: NSRect(x: 100, y: 100, width: 700, height: 600))
        let controller = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 300, height: 64),
            fallbackExpandedSize: NSSize(width: 700, height: 600)
        )

        controller.setCollapsed(true, animated: false)
        controller.setCollapsed(false, fallbackExpandedSize: NSSize(width: 500, height: 450), animated: false)

        XCTAssertFalse(controller.isCollapsed)
        XCTAssertEqual(window.frame.width, 500, accuracy: 0.5)
        XCTAssertEqual(window.frame.height, 450, accuracy: 0.5)
    }
}
