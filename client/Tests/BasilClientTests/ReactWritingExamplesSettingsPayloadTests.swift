import XCTest
@testable import BasilClient

final class ReactWritingExamplesSettingsPayloadTests: XCTestCase {
    func testApiValueOmitsFilterForAllContext() {
        XCTAssertNil(ReactWritingExamplesFilter.all.apiValue)
    }

    func testApiValueReturnsRawValueForNonAllFilters() {
        XCTAssertEqual(ReactWritingExamplesFilter.emailReply.apiValue, "email_reply")
        XCTAssertEqual(ReactWritingExamplesFilter.emailCompose.apiValue, "email_compose")
        XCTAssertEqual(ReactWritingExamplesFilter.socialMedia.apiValue, "social_media")
        XCTAssertEqual(ReactWritingExamplesFilter.document.apiValue, "document")
    }

    func testFilterRawValueRoundTripsForAllFiveWireStrings() {
        let wireStrings = ["all", "email_reply", "email_compose", "social_media", "document"]
        for wireString in wireStrings {
            XCTAssertEqual(ReactWritingExamplesFilter(rawValue: wireString)?.rawValue, wireString)
        }
    }

    func testUnknownFilterStringFailsToParse() {
        XCTAssertNil(ReactWritingExamplesFilter(rawValue: "slack"))
        XCTAssertNil(ReactWritingExamplesFilter(rawValue: ""))
    }

    @MainActor
    func testDeleteSampleConfirmationAlertHasCancelAndDestructiveDeleteButtons() {
        let alert = SettingsShellWindowController.makeDeleteSampleConfirmationAlert()
        XCTAssertEqual(alert.buttons.count, 2)
        XCTAssertEqual(alert.buttons[0].title, "Cancel")
        XCTAssertEqual(alert.buttons[1].title, "Delete")
        XCTAssertTrue(alert.buttons[1].hasDestructiveAction)
    }

    @MainActor
    func testDeleteAllSamplesConfirmationAlertMessageVariesByFilter() {
        let allAlert = SettingsShellWindowController.makeDeleteAllSamplesConfirmationAlert(filter: .all)
        XCTAssertEqual(allAlert.informativeText, "Are you sure you want to delete all writing samples? This action cannot be undone.")

        let documentAlert = SettingsShellWindowController.makeDeleteAllSamplesConfirmationAlert(filter: .document)
        XCTAssertEqual(documentAlert.informativeText, "Are you sure you want to delete all Document samples? This action cannot be undone.")
        XCTAssertEqual(documentAlert.buttons[1].title, "Delete All")
        XCTAssertTrue(documentAlert.buttons[1].hasDestructiveAction)
    }
}
