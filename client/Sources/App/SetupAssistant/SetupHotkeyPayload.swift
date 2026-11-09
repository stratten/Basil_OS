import Foundation

/// Turns hotkey bindings, clashes and outcomes into the plain dictionaries the setup page receives, and checks the keys the page asks to save.
enum SetupHotkeyPayload {
    static func binding(_ binding: HotkeyBinding) -> [String: Any] {
        var payload: [String: Any] = [
            "key": binding.key,
            "enabled": binding.enabled,
            "modifiers": binding.modifiers,
            "isDoublePress": binding.isDoublePress,
        ]
        if let doublePressKey = binding.doublePressKey {
            payload["doublePressKey"] = doublePressKey
        } else {
            payload["doublePressKey"] = NSNull()
        }
        return payload
    }

    /// One entry per shown row: the person's current keys, every clash they have, and one clash-free replacement when there is a clash and a safe replacement exists. Replacements are chosen row by row against the working set, so approving all of them can never collide.
    static func rows(
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        system: HotkeySystemState
    ) -> [[String: Any]] {
        let conflicts = HotkeyConflictEvaluator.conflicts(bindings: bindings, rows: rows, system: system)
        let conflictedIds = rows.map(\.id).filter { id in conflicts.contains { $0.hotkeyId == id } }
        let alternatives = HotkeyAlternativeResolver.alternatives(for: conflictedIds, bindings: bindings, rows: rows, system: system)
        return rows.map { row in
            let current = bindings[row.id] ?? HotkeyRowCatalog.defaultBinding(for: row.id)
            var entry: [String: Any] = [
                "id": row.id,
                "title": row.title,
                "binding": binding(current),
                "conflicts": conflicts.filter { $0.hotkeyId == row.id }.map(\.payload),
            ]
            if let alternative = alternatives[row.id] {
                entry["alternative"] = binding(alternative)
            } else {
                entry["alternative"] = NSNull()
            }
            return entry
        }
    }

    /// Rejects keys that would misbehave: no key at all, a double-press that is not a modifier, or a plain key with no modifier that would fire while typing. Function keys and double-presses need no modifier.
    static func validate(_ binding: HotkeyBinding) throws {
        if binding.isDoublePress {
            guard let key = binding.doublePressKey, ModifierKey.from(key) != nil else {
                throw SetupHotkeyError.invalidDoublePress
            }
            return
        }
        guard !binding.key.trimmingCharacters(in: .whitespaces).isEmpty else {
            throw SetupHotkeyError.emptyKey
        }
        let hasModifier = binding.modifiers.contains { ModifierKey.from($0) != nil }
        guard hasModifier || HotkeyKeyCodes.isFunctionKey(binding.key) else {
            throw SetupHotkeyError.needsModifier
        }
    }
}

enum SetupHotkeyError: LocalizedError, Equatable {
    case unknownHotkey
    case notLoaded
    case emptyKey
    case invalidDoublePress
    case needsModifier

    var errorDescription: String? {
        switch self {
        case .unknownHotkey:
            return "I don't recognize that hotkey."
        case .notLoaded:
            return "I couldn't read your hotkeys yet. You can see and change them in Settings, Hotkeys."
        case .emptyKey:
            return "That shortcut has no key. Press the keys you want to use."
        case .invalidDoublePress:
            return "I can't use that double-press. Press a modifier key twice, such as Control."
        case .needsModifier:
            return "Add a modifier key such as Control or Option, so this shortcut doesn't fire while you type."
        }
    }

    /// The sentence the page shows for any failure, including a network or decoding error.
    static func message(for error: Error) -> String {
        if let known = error as? SetupHotkeyError, let description = known.errorDescription {
            return description
        }
        return "I couldn't read or save your hotkeys just now. You can change them in Settings, Hotkeys."
    }
}
