import Foundation

/// Proposes a free replacement for a Basil hotkey that clashes. The candidates are fixed, ordered lists, and a candidate is only proposed when the evaluator reports it clash-free for that row.
enum HotkeyAlternativeResolver {
    private static let doublePressOrder = ["control", "option", "command", "shift"]

    private static func doublePress(_ modifier: String) -> HotkeyBinding {
        HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: modifier)
    }

    private static func chord(_ key: String, _ modifiers: [String]) -> HotkeyBinding {
        HotkeyBinding(key: key, enabled: true, modifiers: modifiers, isDoublePress: false, doublePressKey: nil)
    }

    /// The replacements for a row in the order they are tried. An unknown row has none.
    static func candidates(for id: String) -> [HotkeyBinding] {
        switch id {
        case "transcribe_audio", "assistant_session":
            return doublePressOrder.map(doublePress)
        case "agent_task":
            return [
                chord("Space", ["option", "shift"]),
                chord("Space", ["control", "option"]),
                chord("Space", ["control", "shift"]),
                chord("Space", ["command", "option", "shift"]),
            ]
        case "conversation_toggle":
            return [
                chord("C", ["control", "option"]),
                chord("C", ["control", "option", "shift"]),
                chord("V", ["control", "option"]),
            ]
        case "home_board_toggle":
            return [
                chord("H", ["control", "option"]),
                chord("B", ["control", "option", "shift"]),
                chord("J", ["control", "option"]),
            ]
        default:
            return []
        }
    }

    /// The first candidate that is not the row's current keys, shares keys with no other Basil binding, and has no clash. Nil when none qualifies.
    static func alternative(
        for id: String,
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        system: HotkeySystemState
    ) -> HotkeyBinding? {
        guard let current = bindings[id] else { return nil }
        for candidate in candidates(for: id) {
            if HotkeyConflictEvaluator.collides(candidate, current) { continue }
            let conflicts = HotkeyConflictEvaluator.conflicts(replacing: id, with: candidate, in: bindings, rows: rows, system: system)
            if conflicts.isEmpty { return candidate }
        }
        return nil
    }

    /// Alternatives for several rows, chosen one at a time against the working set so no two rows are given the same keys.
    static func alternatives(
        for ids: [String],
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        system: HotkeySystemState
    ) -> [String: HotkeyBinding] {
        var working = bindings
        var chosen: [String: HotkeyBinding] = [:]
        for id in ids {
            guard let candidate = alternative(for: id, bindings: working, rows: rows, system: system) else { continue }
            working[id] = candidate
            chosen[id] = candidate
        }
        return chosen
    }
}
