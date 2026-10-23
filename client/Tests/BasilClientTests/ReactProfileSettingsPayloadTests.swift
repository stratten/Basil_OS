import XCTest
@testable import BasilClient

final class ReactProfileSettingsPayloadTests: XCTestCase {
    func testFieldsPayloadParsesPresentValuesAndDropsBlankStrings() {
        let payload = ReactProfileFieldsPayload(raw: [
            "profile": [
                "fullName": "Ada Lovelace",
                "preferredName": "",
                "email": "ada@example.com",
                "jobTitle": "Engineer",
                "companyName": "Analytical Engines",
                "industry": "   ",
                "formality": "professional",
                "tone": "warm",
                "customInstructions": "Do not use em dashes.",
            ],
        ])
        XCTAssertEqual(payload?.fullName, "Ada Lovelace")
        XCTAssertNil(payload?.preferredName)
        XCTAssertEqual(payload?.email, "ada@example.com")
        XCTAssertNil(payload?.industry)
        XCTAssertEqual(payload?.formality, "professional")
        XCTAssertEqual(payload?.tone, "warm")
        XCTAssertEqual(payload?.customInstructions, "Do not use em dashes.")
    }

    func testFieldsPayloadRejectsUnknownFormalityAndTone() {
        let payload = ReactProfileFieldsPayload(raw: [
            "profile": [
                "formality": "not-a-real-level",
                "tone": "not-a-real-tone",
            ],
        ])
        XCTAssertNil(payload?.formality)
        XCTAssertNil(payload?.tone)
    }

    func testFieldsPayloadRejectsMissingProfileKey() {
        XCTAssertNil(ReactProfileFieldsPayload(raw: ["requestId": "abc"]))
    }

    @MainActor
    func testClearProfileConfirmationNamesAllAffectedData() {
        let alert = SettingsShellWindowController.makeClearProfileConfirmationAlert()

        XCTAssertEqual(alert.messageText, "Delete All Personalization Data?")
        XCTAssertTrue(alert.informativeText.contains("writing samples"))
        XCTAssertTrue(alert.informativeText.contains("communication style"))
        XCTAssertEqual(alert.buttons.map(\.title), ["Cancel", "Delete Everything"])
        XCTAssertTrue(alert.buttons[1].hasDestructiveAction)
    }
}
