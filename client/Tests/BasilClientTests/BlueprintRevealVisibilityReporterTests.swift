import AppKit
import WebKit
import XCTest
@testable import BasilClient

@MainActor
final class BlueprintRevealVisibilityReporterTests: XCTestCase {
    func testWindowCountsAsVisibleOnlyWhenOnScreenAndNotMinimized() {
        XCTAssertTrue(BlueprintRevealPolicy.isEffectivelyVisible(isVisible: true, isMiniaturized: false))
        XCTAssertFalse(BlueprintRevealPolicy.isEffectivelyVisible(isVisible: false, isMiniaturized: false))
        XCTAssertFalse(BlueprintRevealPolicy.isEffectivelyVisible(isVisible: true, isMiniaturized: true))
        XCTAssertFalse(BlueprintRevealPolicy.isEffectivelyVisible(isVisible: false, isMiniaturized: true))
    }

    func testOnlyTheFirstResizeAfterOpeningSkipsTheAnimationAndOnlyWithBlueprintRevealOn() {
        XCTAssertFalse(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: false, blueprintReveal: true))
        XCTAssertTrue(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: true, blueprintReveal: true))
        XCTAssertTrue(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: false, blueprintReveal: false))
        XCTAssertTrue(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: true, blueprintReveal: false))
    }

    func testResizePolicyFollowsTheUsersCurrentSetting() {
        AestheticSystem.loadFromSettings(AppearanceSettings(blueprintReveal: true))
        defer { AestheticSystem.loadFromSettings(AppearanceSettings()) }
        XCTAssertFalse(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: false))

        AestheticSystem.loadFromSettings(AppearanceSettings(blueprintReveal: false))
        XCTAssertTrue(BlueprintRevealPolicy.shouldAnimateResize(hasResizedBefore: false))
    }

    func testVisibilityDetailCarriesTheSettingAtThatMoment() {
        let shown = BlueprintRevealPolicy.visibilityDetail(visible: true, blueprintReveal: true)
        XCTAssertEqual(shown["visible"] as? Bool, true)
        XCTAssertEqual(shown["blueprintReveal"] as? Bool, true)

        let hidden = BlueprintRevealPolicy.visibilityDetail(visible: false, blueprintReveal: false)
        XCTAssertEqual(hidden["visible"] as? Bool, false)
        XCTAssertEqual(hidden["blueprintReveal"] as? Bool, false)
    }

    func testFirstPaintScriptSetsTheFlagTheWebSideReads() {
        XCTAssertEqual(BlueprintRevealPolicy.firstPaintScriptSource(enabled: true), "window.basilBlueprintReveal = true;")
        XCTAssertEqual(BlueprintRevealPolicy.firstPaintScriptSource(enabled: false), "window.basilBlueprintReveal = false;")
    }

    func testDispatchFunctionRaisesTheWindowEventTheWebSideListensFor() {
        XCTAssertTrue(BlueprintRevealVisibilityReporter.dispatchFunction.contains("'basil-window-visibility'"))
        XCTAssertTrue(BlueprintRevealVisibilityReporter.dispatchFunction.contains("new CustomEvent"))
    }

    func testWebViewsAreFoundAtAnyDepthAndAreNotInventedForPlainViews() {
        let container = NSView()
        let nested = NSView()
        let first = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        let second = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        container.addSubview(first)
        container.addSubview(nested)
        nested.addSubview(second)

        let found = BlueprintRevealVisibilityReporter.webViews(in: container)
        XCTAssertEqual(found.count, 2)
        XCTAssertTrue(found.contains(first))
        XCTAssertTrue(found.contains(second))
        XCTAssertEqual(BlueprintRevealVisibilityReporter.webViews(in: first), [first])
        XCTAssertTrue(BlueprintRevealVisibilityReporter.webViews(in: NSView()).isEmpty)
        XCTAssertTrue(BlueprintRevealVisibilityReporter.webViews(in: nil).isEmpty)
    }

    func testInstallingTwiceOnTheSameWindowKeepsTheFirstReporter() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 100, height: 100), styleMask: [.borderless], backing: .buffered, defer: true)
        BlueprintRevealVisibilityReporter.install(on: window)
        let first = BlueprintRevealVisibilityReporter.installedReporter(on: window)

        BlueprintRevealVisibilityReporter.install(on: window)
        let second = BlueprintRevealVisibilityReporter.installedReporter(on: window)

        XCTAssertNotNil(first)
        XCTAssertTrue(first === second)
    }

    func testTheSharedWindowConfigurationHelpersInstallTheReporter() {
        let floating = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 100, height: 100), styleMask: [.borderless], backing: .buffered, defer: true)
        floating.configureFloatingWidget()
        XCTAssertNotNil(BlueprintRevealVisibilityReporter.installedReporter(on: floating))

        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 100, height: 100), styleMask: [.borderless], backing: .buffered, defer: true)
        panel.configureMiniPanel(title: "Mini")
        XCTAssertNotNil(BlueprintRevealVisibilityReporter.installedReporter(on: panel))

        let custom = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 100, height: 100), styleMask: [.borderless], backing: .buffered, defer: true)
        custom.configureCustomChromeWindow(title: "Custom", releasedWhenClosed: false)
        XCTAssertNotNil(BlueprintRevealVisibilityReporter.installedReporter(on: custom))
    }

    func testChromeAppearanceInstallsTheReporterOnTheWindow() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 100, height: 100), styleMask: [.borderless], backing: .buffered, defer: true)
        WebKitWindowChromeAppearance.apply(to: window)

        XCTAssertNotNil(BlueprintRevealVisibilityReporter.installedReporter(on: window))
    }
}
