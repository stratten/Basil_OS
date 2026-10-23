import Foundation

/// Parses the display string produced by `HotkeyTextField` (e.g. "⌥F8",
/// "⌘+⌘", "⇧⏎") into a structured `HotkeyBinding`. This is the exact parsing
/// logic that used to live inline in `HotkeySettingsViewModel.updateHotkey`.
/// It now consumes all leading modifiers in capture order, so both the
/// legacy SwiftUI tab and new React bridge controller share a parser that
/// correctly supports multi-modifier bindings.
enum HotkeyBindingParser {
    /// - Parameters:
    ///   - displayString: raw captured string from `HotkeyTextField.stringValue`.
    ///   - enabled: the `enabled` flag to carry into the resulting binding
    ///     (capture never changes `enabled`; callers pass through the
    ///     existing value for this row).
    static func parse(displayString: String, enabled: Bool) -> HotkeyBinding {
        let modifierSymbols = [
            "⌘": "command",
            "⌃": "control",
            "⌥": "option",
            "⇧": "shift",
        ]

        var modifiers: [String] = []
        var cleanKey = displayString
        var isDoublePress = false
        var doublePressKey: String? = nil

        let doublePressPatterns = [
            ("⌥+⌥", "option"),
            ("⌘+⌘", "command"),
            ("⌃+⌃", "control"),
            ("⇧+⇧", "shift"),
        ]

        for (pattern, modifierName) in doublePressPatterns {
            if displayString == pattern {
                isDoublePress = true
                doublePressKey = modifierName
                cleanKey = ""
                break
            }
        }

        if !isDoublePress {
            while let (symbol, name) = modifierSymbols.first(where: { cleanKey.hasPrefix($0.key) }) {
                modifiers.append(name)
                cleanKey.removeFirst(symbol.count)
            }
        }

        return HotkeyBinding(
            key: cleanKey,
            enabled: enabled,
            modifiers: modifiers,
            isDoublePress: isDoublePress,
            doublePressKey: doublePressKey
        )
    }
}
