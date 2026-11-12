import Foundation

/// A Basil hotkey that shares its keys with a macOS shortcut the user has turned on.
struct SystemShortcutConflict: Equatable {
    enum Certainty: String {
        /// The macOS shortcut and the Basil binding are the same keys.
        case exact
        /// The macOS shortcut is on, but its keys are stored in a format this code cannot read, so only the kind of key is known.
        case possible
    }

    let hotkeyId: String
    let source: String
    let certainty: Certainty
    let message: String

    var payload: [String: Any] {
        ["hotkeyId": hotkeyId, "source": source, "certainty": certainty.rawValue, "message": message]
    }
}

/// Reads the macOS keyboard shortcut preferences and reports which Basil hotkeys collide with the ones that are turned on.
///
/// The detection is read-only: it never changes a macOS setting. Spotlight, input source and Dictation shortcuts that use a key are stored as a key code plus a modifier mask, so they are compared exactly. Dictation can also be set to start when one modifier key is pressed twice, which is stored as the modifier alone, so a Basil double-press on the same modifier is reported as a possible conflict. Siri's shortcut is stored in a Siri-specific format, so an unreadable value is reported as a possible conflict with the keys Siri's options use (a doubled Command, or a held Command or Option with Space). On macOS 15 through 26 Siri's shortcut is on by default as a doubled Command, and Siri may write no preference until someone changes it, so a Mac with no Siri shortcut preference and Siri turned on is treated as having that default. A Dictation shortcut on a doubled Command is stored as the plain Command flag, or with extra low bits when it is limited to the left or right Command key, so only the modifier bits are compared.
enum SystemShortcutConflictDetector {
    private static let spaceKeyCode = 49
    private static let modifierBits: [String: Int] = [
        "shift": 131_072,
        "control": 262_144,
        "option": 524_288,
        "command": 1_048_576,
    ]
    static let modifierMask = modifierBits.values.reduce(0, |)

    private static let symbolicShortcutSources: [String: String] = [
        "60": "the macOS input source shortcut",
        "61": "the macOS input source shortcut",
        "64": "Spotlight",
        "65": "Spotlight",
        "164": dictationSource,
    ]

    /// The symbolic hotkey macOS keeps for Dictation. Its entry is a key plus modifiers when customized, or a single modifier (type "modifier") for the press-a-modifier-twice choices.
    private static let siriShortcutKeys = ["KeyboardShortcutSAE", "KeyboardShortcutPreSAE"]
    private static let assistantEnabledKey = "AssistantEnabled"
    /// The macOS versions where Siri's keyboard shortcut is on by default as a doubled Command. macOS 27 removed it.
    private static let siriDefaultShortcutVersions = 15...26

    static var currentMacOSMajorVersion: Int {
        ProcessInfo.processInfo.operatingSystemVersion.majorVersion
    }

    private static let dictationIdentifier = "164"
    private static let dictationSource = "the macOS Dictation shortcut"

    static func conflicts(
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        symbolicHotKeys: [String: Any]?,
        siriPreferences: [String: Any]?,
        macOSMajorVersion: Int = currentMacOSMajorVersion
    ) -> [SystemShortcutConflict] {
        var found: [SystemShortcutConflict] = []

        for row in rows {
            guard let binding = bindings[row.id], binding.enabled else { continue }
            let name = "\(row.title) (\(binding.displayString))"

            if !binding.isDoublePress, let mask = bindingMask(binding), binding.key.caseInsensitiveCompare("Space") == .orderedSame {
                for (identifier, source) in symbolicShortcutSources.sorted(by: { $0.key < $1.key }) {
                    guard let entry = symbolicHotKeys?[identifier] as? [String: Any],
                          isEnabled(entry["enabled"]),
                          let parameters = (entry["value"] as? [String: Any])?["parameters"] as? [Any],
                          parameters.count >= 3,
                          intValue(parameters[1]) == spaceKeyCode,
                          let systemMask = intValue(parameters[2]),
                          systemMask & modifierMask == mask else { continue }
                    found.append(SystemShortcutConflict(
                        hotkeyId: row.id,
                        source: source,
                        certainty: .exact,
                        message: "\(name) is also used by \(source). Choose another shortcut for it here, or change the macOS shortcut in System Settings, Keyboard, Keyboard Shortcuts."
                    ))
                }
            }

            if binding.isDoublePress, let mask = doublePressMask(binding), dictationUsesModifier(mask, symbolicHotKeys) {
                found.append(SystemShortcutConflict(
                    hotkeyId: row.id,
                    source: dictationSource,
                    certainty: .possible,
                    message: "\(name) uses the same modifier key as the macOS Dictation shortcut, which is turned on. If Dictation starts when you use this hotkey, choose another shortcut for it here, or change the Dictation shortcut in System Settings, Keyboard, Dictation."
                ))
            }

            if let siriEntry = enabledSiriShortcut(siriPreferences) {
                if let siriMask = standardSpaceMask(siriEntry) {
                    if !binding.isDoublePress,
                       binding.key.caseInsensitiveCompare("Space") == .orderedSame,
                       bindingMask(binding) == siriMask {
                        found.append(SystemShortcutConflict(
                            hotkeyId: row.id,
                            source: "Siri",
                            certainty: .exact,
                            message: "\(name) is also Siri's keyboard shortcut. Choose another shortcut for it here, or change Siri's shortcut in System Settings, Siri."
                        ))
                    }
                } else if usesKeysSiriCanUse(binding) {
                    found.append(SystemShortcutConflict(
                        hotkeyId: row.id,
                        source: "Siri",
                        certainty: .possible,
                        message: "Siri's keyboard shortcut is turned on, and \(name) uses keys that Siri's shortcut options can also use. If this hotkey also opens Siri, choose another shortcut for it here, or change Siri's shortcut in System Settings, Siri."
                    ))
                }
            } else if usesDoubledCommand(binding), siriShortcutIsOnByDefault(siriPreferences, macOSMajorVersion: macOSMajorVersion) {
                found.append(SystemShortcutConflict(
                    hotkeyId: row.id,
                    source: "Siri",
                    certainty: .possible,
                    message: "Siri's keyboard shortcut is on by default on this version of macOS, and its default is pressing Command twice, which is also \(name). If Siri opens when you use this hotkey, choose another shortcut for it here, or change Siri's shortcut in System Settings, Apple Intelligence & Siri."
                ))
            }
        }
        return found
    }

    /// Conflicts between Basil's default hotkeys and the live macOS shortcuts, as web payloads. Used by setup, which runs before anyone has customized a hotkey.
    static func defaultHotkeyConflictPayloads() -> [[String: Any]] {
        let rows = HotkeyRowCatalog.rows
        let bindings = Dictionary(uniqueKeysWithValues: rows.map { ($0.id, HotkeyRowCatalog.defaultBinding(for: $0.id)) })
        let state = readSystemState()
        return conflicts(bindings: bindings, rows: rows, symbolicHotKeys: state.symbolicHotKeys, siriPreferences: state.siriPreferences).map(\.payload)
    }

    /// The live macOS state. Both reads return nil when the preference does not exist, which means no shortcut is on.
    static func readSystemState() -> (symbolicHotKeys: [String: Any]?, siriPreferences: [String: Any]?) {
        let symbolic = CFPreferencesCopyAppValue("AppleSymbolicHotKeys" as CFString, "com.apple.symbolichotkeys" as CFString) as? [String: Any]
        var siri: [String: Any] = [:]
        for key in siriShortcutKeys {
            if let value = CFPreferencesCopyAppValue(key as CFString, "com.apple.Siri" as CFString) {
                siri[key] = value
            }
        }
        if let assistantEnabled = CFPreferencesCopyAppValue("Assistant Enabled" as CFString, "com.apple.assistant.support" as CFString) {
            siri[assistantEnabledKey] = assistantEnabled
        }
        return (symbolic, siri.isEmpty ? nil : siri)
    }

    static func bindingMask(_ binding: HotkeyBinding) -> Int? {
        var mask = 0
        for modifier in binding.modifiers {
            switch modifier.lowercased() {
            case "alt": mask |= modifierBits["option"] ?? 0
            case "cmd": mask |= modifierBits["command"] ?? 0
            case "ctrl": mask |= modifierBits["control"] ?? 0
            default:
                guard let bit = modifierBits[modifier.lowercased()] else { return nil }
                mask |= bit
            }
        }
        return mask
    }

    /// The modifier flag for a double-press binding's key, or nil when the key is not one macOS stores a modifier shortcut for.
    private static func doublePressMask(_ binding: HotkeyBinding) -> Int? {
        guard let key = binding.doublePressKey.flatMap(ModifierKey.from) else { return nil }
        return modifierBits[key.rawValue]
    }

    /// True when Dictation is on and set to a lone modifier key, and that modifier is `mask`.
    private static func dictationUsesModifier(_ mask: Int, _ symbolicHotKeys: [String: Any]?) -> Bool {
        guard let entry = symbolicHotKeys?[dictationIdentifier] as? [String: Any],
              isEnabled(entry["enabled"]),
              let value = entry["value"] as? [String: Any],
              (value["type"] as? String) == "modifier",
              let parameters = value["parameters"] as? [Any],
              let first = parameters.first,
              let storedModifier = intValue(first),
              storedModifier & modifierMask == mask else { return false }
        return true
    }

    private static func enabledSiriShortcut(_ preferences: [String: Any]?) -> [String: Any]? {
        for key in siriShortcutKeys {
            if let entry = preferences?[key] as? [String: Any], isEnabled(entry["enabled"]) {
                return entry
            }
        }
        return nil
    }

    /// The modifier mask when Siri's shortcut is stored as a standard key code plus modifiers on Space, otherwise nil.
    private static func standardSpaceMask(_ entry: [String: Any]) -> Int? {
        guard let value = entry["value"] as? [String: Any],
              (value["type"] as? String) == "standard",
              let parameters = value["parameters"] as? [Any],
              parameters.count >= 3,
              intValue(parameters[1]) == spaceKeyCode,
              let mask = intValue(parameters[2]) else { return nil }
        return mask & modifierMask
    }

    private static func usesDoubledCommand(_ binding: HotkeyBinding) -> Bool {
        binding.isDoublePress && binding.doublePressKey?.lowercased() == "command"
    }

    /// True when this Mac has no Siri shortcut preference at all, Siri has not been turned off, and the macOS version turns the doubled-Command shortcut on by default.
    private static func siriShortcutIsOnByDefault(_ preferences: [String: Any]?, macOSMajorVersion: Int) -> Bool {
        guard siriDefaultShortcutVersions.contains(macOSMajorVersion) else { return false }
        if let assistantEnabled = preferences?[assistantEnabledKey] as? NSNumber, !assistantEnabled.boolValue { return false }
        return !siriShortcutKeys.contains { preferences?[$0] != nil }
    }

    private static func usesKeysSiriCanUse(_ binding: HotkeyBinding) -> Bool {
        if binding.isDoublePress {
            return usesDoubledCommand(binding)
        }
        guard binding.key.caseInsensitiveCompare("Space") == .orderedSame else { return false }
        let modifiers = Set(binding.modifiers.map { $0.lowercased() })
        return modifiers == ["command"] || modifiers == ["option"]
    }

    static func isEnabled(_ value: Any?) -> Bool {
        (value as? NSNumber)?.boolValue ?? false
    }

    static func intValue(_ value: Any) -> Int? {
        (value as? NSNumber)?.intValue
    }
}
