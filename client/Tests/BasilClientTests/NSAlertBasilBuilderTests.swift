import AppKit
import XCTest
@testable import BasilClient

@MainActor
final class NSAlertBasilBuilderTests: XCTestCase {
    func testPassesTitleAndMessageThrough() {
        let alert = NSAlert(title: "Remove Thing?", message: "It will be gone.", buttons: ["Remove", "Cancel"])

        XCTAssertEqual(alert.messageText, "Remove Thing?")
        XCTAssertEqual(alert.informativeText, "It will be gone.")
    }

    func testStyleDefaultsToWarningAndHonorsExplicitStyles() {
        XCTAssertEqual(NSAlert(title: "T", message: "M", buttons: ["OK"]).alertStyle, .warning)
        XCTAssertEqual(NSAlert(title: "T", message: "M", style: .informational, buttons: ["OK"]).alertStyle, .informational)
        XCTAssertEqual(NSAlert(title: "T", message: "M", style: .critical, buttons: ["OK"]).alertStyle, .critical)
    }

    func testButtonsKeepTheGivenOrderAndDefaultToNonDestructive() {
        let alert = NSAlert(title: "T", message: "M", buttons: ["Open System Settings", "Cancel"])

        XCTAssertEqual(alert.buttons.map(\.title), ["Open System Settings", "Cancel"])
        XCTAssertFalse(alert.buttons[0].hasDestructiveAction)
        XCTAssertFalse(alert.buttons[1].hasDestructiveAction)
    }

    func testDestructiveFlagIsSetOnlyOnTheIndexedButton() {
        let alert = NSAlert(title: "T", message: "M", buttons: ["Cancel", "Delete"], destructiveButtonIndex: 1)

        XCTAssertFalse(alert.buttons[0].hasDestructiveAction)
        XCTAssertTrue(alert.buttons[1].hasDestructiveAction)
    }

    func testOutOfRangeDestructiveIndexSetsNoFlagAndDoesNotCrash() {
        let alert = NSAlert(title: "T", message: "M", buttons: ["Cancel", "Delete"], destructiveButtonIndex: 5)

        XCTAssertEqual(alert.buttons.count, 2)
        XCTAssertFalse(alert.buttons.contains { $0.hasDestructiveAction })
    }

    func testEmptyButtonListLeavesTheAppKitDefaultOKButton() {
        let alert = NSAlert(title: "T", message: "M", buttons: [])

        XCTAssertEqual(alert.buttons.map(\.title), ["OK"], "AppKit supplies a single OK button when none were added.")
        XCTAssertFalse(alert.buttons[0].hasDestructiveAction)
    }

    func testLongMultilineAndSpecialCharacterTextIsUnchanged() {
        let message = """
        Line one with "quotes" and an apostrophe's.

        • Bullet with unicode — and emoji 🧪
        \(String(repeating: "long ", count: 400))
        """
        let alert = NSAlert(title: "Delete \"Model \\ Name\"?", message: message, buttons: ["OK"])

        XCTAssertEqual(alert.messageText, "Delete \"Model \\ Name\"?")
        XCTAssertEqual(alert.informativeText, message)
    }

    func testDeleteModelFactoryUsesTheBuilderWithoutADestructiveButton() {
        let alert = ModelsSettingsAlertFactory.makeDeleteModelConfirmationAlert(modelName: "Whisper \"Large\"", modelSize: nil)

        XCTAssertEqual(alert.messageText, "Delete \"Whisper \"Large\"\"?")
        XCTAssertEqual(alert.informativeText, ModelsSettingsAlertFactory.informativeText(modelSize: nil))
        XCTAssertEqual(alert.alertStyle, .warning)
        XCTAssertEqual(alert.buttons.map(\.title), ["Delete", "Cancel"])
        XCTAssertFalse(alert.buttons.contains { $0.hasDestructiveAction })
    }
}
