import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class WindowRecipeHelpersTests: XCTestCase {
    // The windows are never ordered front, so they are not closed: closing a window that keeps the AppKit default
    // `isReleasedWhenClosed = true` under ARC double-releases it.
    private let panelStyleMask: NSWindow.StyleMask = [.nonactivatingPanel, .borderless]

    private func makePanel() -> NSPanel {
        NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 280, height: 220),
            styleMask: panelStyleMask,
            backing: .buffered,
            defer: false
        )
    }

    private func makeWindow() -> NSWindow {
        NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 200),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
    }

    private func assertSamePanelState(_ lhs: NSPanel, _ rhs: NSPanel, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(lhs.title, rhs.title, file: file, line: line)
        XCTAssertEqual(lhs.level, rhs.level, file: file, line: line)
        XCTAssertEqual(lhs.collectionBehavior, rhs.collectionBehavior, file: file, line: line)
        XCTAssertEqual(lhs.isFloatingPanel, rhs.isFloatingPanel, file: file, line: line)
        XCTAssertEqual(lhs.hidesOnDeactivate, rhs.hidesOnDeactivate, file: file, line: line)
        XCTAssertEqual(lhs.becomesKeyOnlyIfNeeded, rhs.becomesKeyOnlyIfNeeded, file: file, line: line)
        XCTAssertEqual(lhs.worksWhenModal, rhs.worksWhenModal, file: file, line: line)
        XCTAssertEqual(lhs.hasShadow, rhs.hasShadow, file: file, line: line)
        XCTAssertEqual(lhs.isOpaque, rhs.isOpaque, file: file, line: line)
        XCTAssertEqual(lhs.backgroundColor, rhs.backgroundColor, file: file, line: line)
        XCTAssertEqual(lhs.alphaValue, rhs.alphaValue, file: file, line: line)
        XCTAssertEqual(lhs.isMovableByWindowBackground, rhs.isMovableByWindowBackground, file: file, line: line)
        XCTAssertEqual(lhs.isReleasedWhenClosed, rhs.isReleasedWhenClosed, file: file, line: line)
    }

    func testAppKitDefaultsTheRecipesRelyOn() {
        let panel = makePanel()
        XCTAssertEqual(panel.alphaValue, 1.0, "The mini panels drop their explicit alphaValue = 1.0 because this is already the default.")
        XCTAssertFalse(panel.isReleasedWhenClosed, "NSPanel defaults to not released when closed, so a nil releasedWhenClosed must leave that default alone.")
    }

    func testMiniPanelMatchesTheLegacyClearPanelBlock() {
        let legacy = makePanel()
        legacy.title = "Scheduled Runs"
        legacy.level = .floating
        legacy.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        legacy.isFloatingPanel = true
        legacy.hidesOnDeactivate = false
        legacy.becomesKeyOnlyIfNeeded = true
        legacy.worksWhenModal = true
        legacy.hasShadow = false
        legacy.alphaValue = 1.0
        legacy.isOpaque = false
        legacy.backgroundColor = NSColor.clear
        legacy.isMovableByWindowBackground = true

        let panel = makePanel()
        panel.configureMiniPanel(title: "Scheduled Runs", transparency: .clearWithoutShadow)

        assertSamePanelState(panel, legacy)
    }

    func testMiniPanelMatchesTheLegacyInheritedTransparencyBlock() {
        let legacy = makePanel()
        legacy.title = "Proactive Suggestions"
        legacy.level = .floating
        legacy.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        legacy.isFloatingPanel = true
        legacy.hidesOnDeactivate = false
        legacy.becomesKeyOnlyIfNeeded = true
        legacy.worksWhenModal = true
        legacy.isMovableByWindowBackground = true

        let panel = makePanel()
        panel.configureMiniPanel(title: "Proactive Suggestions")

        assertSamePanelState(panel, legacy)
    }

    func testMiniPanelMatchesTheLegacyResumeToastBlock() {
        let legacy = makePanel()
        legacy.title = "Resume Setup"
        legacy.level = .floating
        legacy.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        legacy.isFloatingPanel = true
        legacy.hidesOnDeactivate = false
        legacy.becomesKeyOnlyIfNeeded = true
        legacy.worksWhenModal = true
        legacy.isReleasedWhenClosed = false
        legacy.isMovableByWindowBackground = true

        let panel = makePanel()
        panel.configureMiniPanel(title: "Resume Setup", ignoresWindowCycling: false, releasedWhenClosed: false)

        assertSamePanelState(panel, legacy)
        XCTAssertFalse(panel.collectionBehavior.contains(.ignoresCycle))
        XCTAssertTrue(panel.collectionBehavior.contains(.stationary))
    }

    func testFloatingWidgetKeepsIgnoresCycleByDefault() {
        let window = makeWindow()
        window.configureFloatingWidget()
        XCTAssertTrue(window.collectionBehavior.contains(.ignoresCycle))

        let other = makeWindow()
        other.configureFloatingWidget(ignoresWindowCycling: false)
        XCTAssertFalse(other.collectionBehavior.contains(.ignoresCycle))
        XCTAssertEqual(other.collectionBehavior, [.canJoinAllSpaces, .fullScreenAuxiliary])
    }

    func testCustomChromeWindowMatchesTheLegacyBlock() {
        let legacy = makeWindow()
        legacy.title = "Settings"
        legacy.isReleasedWhenClosed = false
        legacy.isMovableByWindowBackground = true

        let window = makeWindow()
        window.configureCustomChromeWindow(title: "Settings", releasedWhenClosed: false)

        XCTAssertEqual(window.title, legacy.title)
        XCTAssertEqual(window.isReleasedWhenClosed, legacy.isReleasedWhenClosed)
        XCTAssertEqual(window.isMovableByWindowBackground, legacy.isMovableByWindowBackground)
        XCTAssertEqual(window.level, legacy.level)
        XCTAssertEqual(window.collectionBehavior, legacy.collectionBehavior)
        XCTAssertEqual(window.hidesOnDeactivate, legacy.hidesOnDeactivate)
    }

    func testCustomChromeWindowHonorsTheReleasedWhenClosedChoice() {
        let retained = makeWindow()
        retained.configureCustomChromeWindow(title: "Upload Audio File", releasedWhenClosed: true)
        XCTAssertTrue(retained.isReleasedWhenClosed)
        XCTAssertEqual(retained.title, "Upload Audio File")

        let owned = makeWindow()
        owned.configureCustomChromeWindow(title: "Basil's Capabilities", releasedWhenClosed: false)
        XCTAssertFalse(owned.isReleasedWhenClosed)
        XCTAssertEqual(owned.title, "Basil's Capabilities")
    }
}
