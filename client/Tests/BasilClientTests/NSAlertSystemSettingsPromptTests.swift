import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class NSAlertSystemSettingsPromptTests: XCTestCase {
    func testFirstButtonOpensTheRequestedPaneAndReturnsTrue() {
        var opened: [SystemSettingsPrivacyPane] = []

        let result = NSAlert.runSystemSettingsPrompt(
            title: "Microphone Access Required",
            message: "Open it?",
            declineTitle: "Cancel",
            pane: .microphone,
            present: { _ in .alertFirstButtonReturn },
            open: { opened.append($0); return true }
        )

        XCTAssertTrue(result)
        XCTAssertEqual(opened, [.microphone])
    }

    func testSecondButtonDoesNotOpenAnythingAndReturnsFalse() {
        var openCalls = 0

        let result = NSAlert.runSystemSettingsPrompt(
            title: "T",
            message: "M",
            declineTitle: "Continue Without Permission",
            pane: .accessibility,
            present: { _ in .alertSecondButtonReturn },
            open: { _ in openCalls += 1; return true }
        )

        XCTAssertFalse(result)
        XCTAssertEqual(openCalls, 0)
    }

    func testFailedOpenReturnsFalse() {
        let result = NSAlert.runSystemSettingsPrompt(
            title: "T",
            message: "M",
            declineTitle: "Cancel",
            pane: .screenRecording,
            present: { _ in .alertFirstButtonReturn },
            open: { _ in false }
        )

        XCTAssertFalse(result)
    }

    func testAlertContentsArePassedThrough() {
        var captured: NSAlert?

        NSAlert.runSystemSettingsPrompt(
            title: "App Restart Required",
            message: "Line one.\n\nLine two with \"quotes\".",
            style: .informational,
            declineTitle: "I'll Restart Manually",
            pane: .accessibility,
            present: { captured = $0; return .alertSecondButtonReturn },
            open: { _ in true }
        )

        XCTAssertEqual(captured?.messageText, "App Restart Required")
        XCTAssertEqual(captured?.informativeText, "Line one.\n\nLine two with \"quotes\".")
        XCTAssertEqual(captured?.alertStyle, .informational)
        XCTAssertEqual(captured?.buttons.map(\.title), ["Open System Settings", "I'll Restart Manually"])
    }

    func testStyleDefaultsToWarning() {
        var captured: NSAlert?

        NSAlert.runSystemSettingsPrompt(
            title: "T",
            message: "M",
            declineTitle: "Cancel",
            pane: .inputMonitoring,
            present: { captured = $0; return .alertSecondButtonReturn },
            open: { _ in true }
        )

        XCTAssertEqual(captured?.alertStyle, .warning)
    }
}
