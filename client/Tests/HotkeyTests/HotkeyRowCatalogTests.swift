import XCTest
@testable import BasilClient

@MainActor
final class HotkeyRowCatalogTests: XCTestCase {
    func testHomeBoardToggleRowIsRegistered() {
        let row = HotkeyRowCatalog.rows.first { $0.id == "home_board_toggle" }

        XCTAssertEqual(row?.title, "Open Basil Home")
        XCTAssertEqual(row?.subtitle, "Show or hide the Basil Home board")
    }

    func testHomeBoardToggleDefaultBindingIsControlOptionB() {
        let binding = HotkeyRowCatalog.defaultBinding(for: "home_board_toggle")

        XCTAssertTrue(binding.enabled)
        XCTAssertEqual(binding.key, "B")
        XCTAssertEqual(binding.modifiers, ["control", "option"])
        XCTAssertFalse(binding.isDoublePress)
        XCTAssertNil(binding.doublePressKey)
    }

    func testEnabledHomeBoardToggleRegistersAHotKey() {
        let service = HotkeyService()
        service.isEnabled = true
        service.configureHotkeys(with: [
            "home_board_toggle": HotkeyBinding(key: "F9", enabled: true, modifiers: []),
        ])

        XCTAssertNotNil(service.hotkeys["home_board_toggle"])
    }

    func testDisabledHomeBoardToggleDoesNotRegisterAHotKey() {
        let service = HotkeyService()
        service.isEnabled = true
        service.configureHotkeys(with: [
            "home_board_toggle": HotkeyBinding(key: "B", enabled: false, modifiers: ["control", "option"]),
        ])

        XCTAssertNil(service.hotkeys["home_board_toggle"])
    }
}
