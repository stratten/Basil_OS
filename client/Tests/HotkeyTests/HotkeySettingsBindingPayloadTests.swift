import XCTest
@testable import BasilClient

final class HotkeySettingsBindingPayloadTests: XCTestCase {
    func testPreservesBackendDescriptionWhenApplyingReactBinding() {
        let payload = HotkeySettingsBindingPayload(raw: [
            "key": "F8",
            "enabled": true,
            "modifiers": ["option"],
            "isDoublePress": false,
            "doublePressKey": NSNull(),
        ])

        let binding = payload?.toHotkeyBinding(preservingDescription: "Conversation toggle")

        XCTAssertEqual(binding?.key, "F8")
        XCTAssertEqual(binding?.modifiers, ["option"])
        XCTAssertEqual(binding?.hotkeyDescription, "Conversation toggle")
    }
}
