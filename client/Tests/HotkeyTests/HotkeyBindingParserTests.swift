import XCTest
@testable import BasilClient

final class HotkeyBindingParserTests: XCTestCase {
    func testParsesTraditionalMultiModifierBindingInCaptureOrder() {
        let binding = HotkeyBindingParser.parse(displayString: "⌘⌃⌥⇧F8", enabled: true)

        XCTAssertEqual(binding.key, "F8")
        XCTAssertEqual(binding.modifiers, ["command", "control", "option", "shift"])
        XCTAssertTrue(binding.enabled)
        XCTAssertFalse(binding.isDoublePress)
        XCTAssertNil(binding.doublePressKey)
    }

    func testParsesDoublePressBinding() {
        let binding = HotkeyBindingParser.parse(displayString: "⌥+⌥", enabled: false)

        XCTAssertEqual(binding.key, "")
        XCTAssertEqual(binding.modifiers, [])
        XCTAssertFalse(binding.enabled)
        XCTAssertTrue(binding.isDoublePress)
        XCTAssertEqual(binding.doublePressKey, "option")
    }

    func testParsesOptionSpaceAsAnEnabledTraditionalBinding() {
        let binding = HotkeyBindingParser.parse(displayString: "⌥Space", enabled: true)

        XCTAssertEqual(binding.key, "Space")
        XCTAssertEqual(binding.modifiers, ["option"])
        XCTAssertTrue(binding.enabled)
        XCTAssertFalse(binding.isDoublePress)
    }
}
