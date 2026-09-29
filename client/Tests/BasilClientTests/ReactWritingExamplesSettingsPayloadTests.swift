import XCTest
import WebKit
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

    @MainActor
    func testUpdateSampleIntentInvokesHandlerWithContent() {
        let bridge = ReactWritingExamplesSettingsWebView(
            webView: WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        )
        var received: (requestId: String, id: String, content: String, contextType: String, recipient: String)?
        bridge.onRequestUpdateSample = { requestId, id, content, contextType, recipient in
            received = (requestId, id, content, contextType, recipient)
        }

        bridge.handleIntent([
            "type": "requestUpdateSample",
            "requestId": "request-1",
            "id": "sample-1",
            "content": "Updated sample",
            "contextType": "document",
            "recipient": "",
        ])

        XCTAssertEqual(received?.requestId, "request-1")
        XCTAssertEqual(received?.id, "sample-1")
        XCTAssertEqual(received?.content, "Updated sample")
        XCTAssertEqual(received?.contextType, "document")
        XCTAssertEqual(received?.recipient, "")
    }

    @MainActor
    func testAddSampleIntentInvokesHandlerWithOptionalRecipient() {
        let bridge = ReactWritingExamplesSettingsWebView(
            webView: WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        )
        var received: (requestId: String, content: String, contextType: String, recipient: String?)?
        bridge.onRequestAddSample = { requestId, content, contextType, recipient in
            received = (requestId, content, contextType, recipient)
        }

        bridge.handleIntent([
            "type": "requestAddSample",
            "requestId": "request-2",
            "content": "New sample",
            "contextType": "document",
            "recipient": "jordan@example.com",
        ])

        XCTAssertEqual(received?.requestId, "request-2")
        XCTAssertEqual(received?.content, "New sample")
        XCTAssertEqual(received?.contextType, "document")
        XCTAssertEqual(received?.recipient, "jordan@example.com")
    }

    @MainActor
    func testMalformedUpdateAndAddSampleIntentsAreReported() {
        let bridge = ReactWritingExamplesSettingsWebView(
            webView: WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        )
        var malformedIntents: [String] = []
        bridge.onMalformedIntent = { malformedIntents.append($0) }

        bridge.handleIntent(["type": "requestUpdateSample", "requestId": "request-1", "id": "sample-1"])
        bridge.handleIntent(["type": "requestAddSample", "requestId": "request-2", "content": "New sample"])
        bridge.handleIntent([
            "type": "requestUpdateSample",
            "requestId": "request-3",
            "id": "sample-1",
            "content": "Updated sample",
            "recipient": "",
        ])

        XCTAssertEqual(malformedIntents, ["requestUpdateSample", "requestAddSample", "requestUpdateSample"])
    }
}
