import Foundation
@testable import BasilClient

enum HotkeyTestSupport {
    static let rows = HotkeyRowCatalog.rows

    /// The table the backend returns for an untouched install: the five shown rows at their defaults plus the three hidden bindings.
    static func defaultTable() -> [String: HotkeyBinding] {
        var table = Dictionary(uniqueKeysWithValues: rows.map { ($0.id, HotkeyRowCatalog.defaultBinding(for: $0.id)) })
        table["capture_screen"] = HotkeyBinding(key: "F1", enabled: true, modifiers: [])
        table["streaming_transcription"] = HotkeyBinding(key: "F5", enabled: true, modifiers: [])
        table["insert_assistant_output"] = HotkeyBinding(key: "F12", enabled: true, modifiers: [])
        return table
    }

    static func title(_ id: String) -> String {
        rows.first { $0.id == id }?.title ?? id
    }

    static func system(
        functionKeysAreStandard: Bool = true,
        symbolic: [String: Any]? = nil,
        siri: [String: Any]? = nil,
        macOSMajorVersion: Int = 27
    ) -> HotkeySystemState {
        HotkeySystemState(symbolicHotKeys: symbolic, siriPreferences: siri, functionKeysAreStandard: functionKeysAreStandard, macOSMajorVersion: macOSMajorVersion)
    }

    static func symbolic(_ identifier: String, keyCode: Int, mask: Int, enabled: Bool = true) -> [String: Any] {
        [identifier: ["enabled": enabled ? 1 : 0, "value": ["type": "standard", "parameters": [65535, keyCode, mask]]]]
    }

    static let unreadableSiri: [String: Any] = ["KeyboardShortcutSAE": ["enabled": 1, "value": ["type": "SAE1.0"]]]

    static func chord(_ key: String, _ modifiers: [String]) -> HotkeyBinding {
        HotkeyBinding(key: key, enabled: true, modifiers: modifiers, isDoublePress: false, doublePressKey: nil)
    }

    static func doublePress(_ modifier: String) -> HotkeyBinding {
        HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: modifier)
    }
}
