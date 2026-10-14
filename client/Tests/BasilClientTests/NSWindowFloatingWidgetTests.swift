import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class NSWindowFloatingWidgetTests: XCTestCase {
    // The windows are never ordered front, so they are not closed: closing a window that keeps the AppKit default
    // `isReleasedWhenClosed = true` under ARC double-releases it, which is the hazard these tests also document.
    private let widgetStyleMask: NSWindow.StyleMask = [.borderless, .resizable, .miniaturizable]

    private func makeWindow() -> CustomBorderlessWindow {
        CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 200),
            styleMask: widgetStyleMask,
            backing: .buffered,
            defer: false
        )
    }

    private func makePanel() -> ClosableBorderlessPanel {
        ClosableBorderlessPanel(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 200),
            styleMask: widgetStyleMask,
            backing: .buffered,
            defer: false
        )
    }

    func testAppKitDefaultsTheHelperReliesOn() {
        let window = makeWindow()
        XCTAssertFalse(window.hidesOnDeactivate)
        XCTAssertEqual(window.alphaValue, 1.0)
        XCTAssertTrue(window.isReleasedWhenClosed)
    }

    func testAppliesSharedBlockWithoutOptionalPieces() {
        let window = makeWindow()
        let originalTitle = window.title
        let originalShadow = window.hasShadow
        let originalOpaque = window.isOpaque
        let originalBackground = window.backgroundColor

        window.configureFloatingWidget()

        XCTAssertEqual(window.level, .floating)
        XCTAssertEqual(window.collectionBehavior, [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle])
        XCTAssertFalse(window.hidesOnDeactivate)
        XCTAssertTrue(window.isMovableByWindowBackground)
        XCTAssertEqual(window.title, originalTitle)
        XCTAssertTrue(window.isReleasedWhenClosed, "A nil releasedWhenClosed must leave the AppKit default untouched.")
        XCTAssertEqual(window.hasShadow, originalShadow)
        XCTAssertEqual(window.isOpaque, originalOpaque)
        XCTAssertEqual(window.backgroundColor, originalBackground)
    }

    func testTitleAndReleasedWhenClosedAreAssignedWhenProvided() {
        let window = makeWindow()

        window.configureFloatingWidget(title: "Conversation", releasedWhenClosed: false)

        XCTAssertEqual(window.title, "Conversation")
        XCTAssertFalse(window.isReleasedWhenClosed)
    }

    func testStationaryIsAddedOnlyWhenRequested() {
        let plain = makeWindow()
        let stationary = makeWindow()

        plain.configureFloatingWidget()
        stationary.configureFloatingWidget(includesStationary: true)

        XCTAssertFalse(plain.collectionBehavior.contains(.stationary))
        XCTAssertEqual(
            stationary.collectionBehavior,
            [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        )
    }

    func testClearWithoutShadowSetsTheTransparentTriple() {
        let window = makeWindow()

        window.configureFloatingWidget(transparency: .clearWithoutShadow)

        XCTAssertFalse(window.hasShadow)
        XCTAssertFalse(window.isOpaque)
        XCTAssertEqual(window.backgroundColor, .clear)
    }

    func testWorksOnClosablePanelWithoutChangingPanelOnlyProperties() {
        let panel = makePanel()
        let originalFloatingPanel = panel.isFloatingPanel
        let originalWorksWhenModal = panel.worksWhenModal

        panel.configureFloatingWidget(title: "Meeting Analysis", transparency: .clearWithoutShadow)
        panel.isFloatingPanel = true

        XCTAssertEqual(panel.title, "Meeting Analysis")
        XCTAssertEqual(panel.level, .floating)
        XCTAssertFalse(panel.hidesOnDeactivate)
        XCTAssertFalse(originalFloatingPanel)
        XCTAssertTrue(panel.isFloatingPanel)
        XCTAssertEqual(panel.worksWhenModal, originalWorksWhenModal)
    }

    func testPanelMatchesTheLegacyInlinePropertyOrder() {
        let legacy = makePanel()
        let shared = makePanel()

        legacy.title = "Meeting Assistant"
        legacy.level = .floating
        legacy.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        legacy.isFloatingPanel = true
        legacy.hidesOnDeactivate = false
        legacy.becomesKeyOnlyIfNeeded = false
        legacy.worksWhenModal = true
        legacy.hasShadow = false
        legacy.isOpaque = false
        legacy.backgroundColor = NSColor.clear
        legacy.isMovableByWindowBackground = true

        shared.configureFloatingWidget(title: "Meeting Assistant", transparency: .clearWithoutShadow)
        shared.isFloatingPanel = true
        shared.becomesKeyOnlyIfNeeded = false
        shared.worksWhenModal = true

        XCTAssertEqual(shared.title, legacy.title)
        XCTAssertEqual(shared.level, legacy.level)
        XCTAssertEqual(shared.collectionBehavior, legacy.collectionBehavior)
        XCTAssertEqual(shared.isFloatingPanel, legacy.isFloatingPanel)
        XCTAssertEqual(shared.hidesOnDeactivate, legacy.hidesOnDeactivate)
        XCTAssertEqual(shared.becomesKeyOnlyIfNeeded, legacy.becomesKeyOnlyIfNeeded)
        XCTAssertEqual(shared.worksWhenModal, legacy.worksWhenModal)
        XCTAssertEqual(shared.hasShadow, legacy.hasShadow)
        XCTAssertEqual(shared.isOpaque, legacy.isOpaque)
        XCTAssertEqual(shared.backgroundColor, legacy.backgroundColor)
        XCTAssertEqual(shared.isMovableByWindowBackground, legacy.isMovableByWindowBackground)
        XCTAssertEqual(shared.isReleasedWhenClosed, legacy.isReleasedWhenClosed)
    }
}
