import XCTest
@testable import BasilClient

final class PowerUserGuideHotkeysTests: XCTestCase {
    private let doubleOption = HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: "option")
    private let optionSpace = HotkeyBinding(key: "space", enabled: false, modifiers: ["option"])

    private func item(_ payload: [String: Any], _ id: String) -> [String: Any]? {
        payload[id] as? [String: Any]
    }

    func testServiceBindingsAreNamedForTheGuide() {
        let payload = PowerUserGuideHotkeys.payload(serviceBindings: ["assistantSession": doubleOption, "agentTask": optionSpace])

        XCTAssertEqual(Set(payload.keys), ["assistantSession", "agentTask"])
        XCTAssertEqual(item(payload, "assistantSession")?["display"] as? String, "⌥⌥")
        XCTAssertEqual(item(payload, "assistantSession")?["isDoublePress"] as? Bool, true)
        XCTAssertEqual(item(payload, "assistantSession")?["doublePressKey"] as? String, "option")
        XCTAssertEqual(item(payload, "agentTask")?["display"] as? String, "⌥␣")
        XCTAssertEqual(item(payload, "agentTask")?["enabled"] as? Bool, false)
        XCTAssertNil(item(payload, "agentTask")?["doublePressKey"])
    }

    func testSettingsBindingsUseTheBackendIdentifiers() {
        let payload = PowerUserGuideHotkeys.payload(settingsBindings: [
            "transcribe_audio": doubleOption,
            "assistant_session": doubleOption,
            "agent_task": optionSpace,
            "conversation_toggle": optionSpace,
            "home_board_toggle": optionSpace,
        ])

        XCTAssertEqual(Set(payload.keys), ["transcription", "assistantSession", "agentTask", "conversation"])
    }

    func testMissingBindingsAreOmittedSoTheGuideFallsBackToItsDefaults() {
        XCTAssertTrue(PowerUserGuideHotkeys.payload(settingsBindings: [:]).isEmpty)
    }
}
