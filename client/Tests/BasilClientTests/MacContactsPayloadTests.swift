import XCTest
@testable import BasilClient

final class MacContactsPayloadTests: XCTestCase {
    func testUpdateRequestParsesEnabledValueAndRequestId() {
        let request = ReactMacContactsSettingsUpdateRequest(raw: [
            "requestId": "contacts-enable-123",
            "enabled": true,
        ])

        XCTAssertEqual(request?.requestId, "contacts-enable-123")
        XCTAssertEqual(request?.enabled, true)
    }

    func testUpdateRequestRejectsBlankRequestId() {
        XCTAssertNil(ReactMacContactsSettingsUpdateRequest(raw: [
            "requestId": "  ",
            "enabled": true,
        ]))
    }

    func testUpdateRequestRejectsMissingOrNonBooleanEnabledValue() {
        XCTAssertNil(ReactMacContactsSettingsUpdateRequest(raw: ["requestId": "contacts-enable-123"]))
        XCTAssertNil(ReactMacContactsSettingsUpdateRequest(raw: [
            "requestId": "contacts-enable-123",
            "enabled": "true",
        ]))
    }
}
