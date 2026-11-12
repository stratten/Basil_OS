import Foundation

enum HotkeyConflictKind: String {
    /// An enabled macOS shortcut uses the same keys.
    case macShortcut = "mac_shortcut"
    /// The key is F1 to F12 and this Mac sends those as media keys unless fn is held.
    case mediaKey = "media_key"
    /// Another Basil binding uses the same keys.
    case basilDuplicate = "basil_duplicate"
}

/// One reason a Basil hotkey needs attention, in words the setup screen can show as written.
struct HotkeyConflict: Equatable {
    let hotkeyId: String
    let kind: HotkeyConflictKind
    let source: String
    let certainty: SystemShortcutConflict.Certainty
    let message: String

    var payload: [String: Any] {
        [
            "hotkeyId": hotkeyId,
            "kind": kind.rawValue,
            "source": source,
            "certainty": certainty.rawValue,
            "message": message,
        ]
    }
}

/// The macOS state the evaluator reads. Tests build this by hand, so the evaluator never has to touch the system.
struct HotkeySystemState {
    var symbolicHotKeys: [String: Any]?
    var siriPreferences: [String: Any]?
    /// True when this Mac sends F1 to F12 as ordinary function keys. When false they act as media keys unless fn is held.
    var functionKeysAreStandard: Bool
    /// The macOS major version, which decides whether Siri's doubled-Command shortcut is on by default. Tests set it so results do not depend on the Mac running them.
    var macOSMajorVersion: Int = SystemShortcutConflictDetector.currentMacOSMajorVersion
}

/// Reports which of the person's Basil hotkeys clash with something else, read-only. It wraps `SystemShortcutConflictDetector` for the Space and Siri cases and adds clashes on any other key, the media keys, and two Basil hotkeys sharing keys.
enum HotkeyConflictEvaluator {
    private static let screenshotShortcut = "the macOS screenshot shortcut"

    private static let macShortcutNames: [String: String] = [
        "27": "the macOS shortcut that moves focus to the next window",
        "28": screenshotShortcut,
        "29": screenshotShortcut,
        "30": screenshotShortcut,
        "31": screenshotShortcut,
        "32": "the macOS shortcut for Mission Control",
        "33": "the macOS shortcut for Application windows",
        "36": "the macOS shortcut for Show Desktop",
        "52": "the macOS shortcut that turns Dock hiding on or off",
        "79": "the macOS shortcut that moves left a space",
        "81": "the macOS shortcut that moves right a space",
        "164": "the macOS Dictation shortcut",
    ]

    private static func macShortcutName(for identifier: String) -> String {
        if let number = Int(identifier), (118...126).contains(number) {
            return "the macOS shortcut that switches to Desktop \(number - 117)"
        }
        return macShortcutNames[identifier] ?? "a macOS keyboard shortcut"
    }

    /// Every clash for the bindings the person has now. Results are in row order, and within a row in the order the checks run.
    static func conflicts(
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        system: HotkeySystemState
    ) -> [HotkeyConflict] {
        var found: [HotkeyConflict] = SystemShortcutConflictDetector.conflicts(
            bindings: bindings,
            rows: rows,
            symbolicHotKeys: system.symbolicHotKeys,
            siriPreferences: system.siriPreferences,
            macOSMajorVersion: system.macOSMajorVersion
        ).map { conflict in
            HotkeyConflict(
                hotkeyId: conflict.hotkeyId,
                kind: .macShortcut,
                source: conflict.source,
                certainty: conflict.certainty,
                message: conflict.message
            )
        }

        for row in rows {
            guard let binding = bindings[row.id], binding.enabled else { continue }
            let name = "\(row.title) (\(binding.displayString))"
            found.append(contentsOf: otherMacShortcutConflicts(row: row, binding: binding, name: name, symbolicHotKeys: system.symbolicHotKeys))
            if let conflict = mediaKeyConflict(row: row, binding: binding, name: name, system: system) {
                found.append(conflict)
            }
            if let conflict = duplicateConflict(row: row, binding: binding, bindings: bindings, rows: rows) {
                found.append(conflict)
            }
        }

        let rowOrder = Dictionary(uniqueKeysWithValues: rows.enumerated().map { ($0.element.id, $0.offset) })
        return found.enumerated().sorted { lhs, rhs in
            let lhsRow = rowOrder[lhs.element.hotkeyId] ?? Int.max
            let rhsRow = rowOrder[rhs.element.hotkeyId] ?? Int.max
            return lhsRow != rhsRow ? lhsRow < rhsRow : lhs.offset < rhs.offset
        }.map { $0.element }
    }

    /// The clashes a proposed binding for one row would have if it replaced that row's current binding. Unlike `conflicts(bindings:rows:system:)`, a clash with any other Basil binding counts, whatever its order, because the proposal is the one being chosen.
    static func conflicts(
        replacing id: String,
        with binding: HotkeyBinding,
        in bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition],
        system: HotkeySystemState
    ) -> [HotkeyConflict] {
        var trial = bindings
        trial[id] = binding
        var result = conflicts(bindings: trial, rows: rows, system: system).filter { $0.hotkeyId == id }
        guard let row = rows.first(where: { $0.id == id }),
              !result.contains(where: { $0.kind == .basilDuplicate }) else { return result }
        let collidingId = bindings.keys.sorted().first { otherId in
            guard otherId != id, let other = bindings[otherId] else { return false }
            return collides(binding, other)
        }
        if let collidingId {
            result.append(duplicateConflict(row: row, binding: binding, otherId: collidingId, rows: rows))
        }
        return result
    }

    /// True when both bindings are on and use the same keys. A double-press only collides with the same double-press.
    static func collides(_ first: HotkeyBinding, _ second: HotkeyBinding) -> Bool {
        guard first.enabled, second.enabled else { return false }
        if first.isDoublePress || second.isDoublePress {
            guard first.isDoublePress, second.isDoublePress,
                  let firstKey = first.doublePressKey.flatMap(ModifierKey.from),
                  let secondKey = second.doublePressKey.flatMap(ModifierKey.from) else { return false }
            return firstKey == secondKey
        }
        guard !first.key.isEmpty, first.key.caseInsensitiveCompare(second.key) == .orderedSame else { return false }
        return normalizedModifiers(first) == normalizedModifiers(second)
    }

    /// The live macOS state. Every read is read-only. A missing function key preference means the Mac's default, which is media keys.
    static func readSystemState() -> HotkeySystemState {
        let state = SystemShortcutConflictDetector.readSystemState()
        let functionKeyValue = CFPreferencesCopyAppValue("com.apple.keyboard.fnState" as CFString, kCFPreferencesAnyApplication)
        return HotkeySystemState(
            symbolicHotKeys: state.symbolicHotKeys,
            siriPreferences: state.siriPreferences,
            functionKeysAreStandard: (functionKeyValue as? NSNumber)?.boolValue ?? false
        )
    }

    private static func normalizedModifiers(_ binding: HotkeyBinding) -> Set<ModifierKey> {
        Set(binding.modifiers.compactMap(ModifierKey.from))
    }

    private static func otherMacShortcutConflicts(
        row: HotkeyRowDefinition,
        binding: HotkeyBinding,
        name: String,
        symbolicHotKeys: [String: Any]?
    ) -> [HotkeyConflict] {
        guard !binding.isDoublePress,
              binding.key.caseInsensitiveCompare("Space") != .orderedSame,
              let keyCode = HotkeyKeyCodes.code(for: binding.key),
              let mask = SystemShortcutConflictDetector.bindingMask(binding),
              let table = symbolicHotKeys else { return [] }

        var result: [HotkeyConflict] = []
        for identifier in table.keys.sorted() {
            guard let entry = table[identifier] as? [String: Any],
                  SystemShortcutConflictDetector.isEnabled(entry["enabled"]),
                  let parameters = (entry["value"] as? [String: Any])?["parameters"] as? [Any],
                  parameters.count >= 3,
                  SystemShortcutConflictDetector.intValue(parameters[1]) == keyCode,
                  let systemMask = SystemShortcutConflictDetector.intValue(parameters[2]),
                  systemMask & SystemShortcutConflictDetector.modifierMask == mask else { continue }
            let source = macShortcutName(for: identifier)
            result.append(HotkeyConflict(
                hotkeyId: row.id,
                kind: .macShortcut,
                source: source,
                certainty: .exact,
                message: "\(name) is also used by \(source). Choose another shortcut for it here, or change the macOS shortcut in System Settings, Keyboard, Keyboard Shortcuts."
            ))
        }
        return result
    }

    private static func mediaKeyConflict(
        row: HotkeyRowDefinition,
        binding: HotkeyBinding,
        name: String,
        system: HotkeySystemState
    ) -> HotkeyConflict? {
        guard !system.functionKeysAreStandard,
              !binding.isDoublePress,
              HotkeyKeyCodes.isFunctionKey(binding.key) else { return nil }
        return HotkeyConflict(
            hotkeyId: row.id,
            kind: .mediaKey,
            source: "this Mac's media keys",
            certainty: .possible,
            message: "On this Mac, \(binding.key.uppercased()) works as a media key (volume, brightness or playback) unless you hold fn, so \(name) will not fire on its own. If your keyboard sends F-keys as ordinary keys, you can keep it."
        )
    }

    private static func duplicateConflict(
        row: HotkeyRowDefinition,
        binding: HotkeyBinding,
        bindings: [String: HotkeyBinding],
        rows: [HotkeyRowDefinition]
    ) -> HotkeyConflict? {
        let shownIds = rows.map(\.id)
        let hiddenIds = bindings.keys.filter { !shownIds.contains($0) }.sorted()
        let priority = hiddenIds + shownIds
        guard let position = priority.firstIndex(of: row.id) else { return nil }
        for otherId in priority[..<position] {
            guard let other = bindings[otherId], collides(binding, other) else { continue }
            return duplicateConflict(row: row, binding: binding, otherId: otherId, rows: rows)
        }
        return nil
    }

    private static func duplicateConflict(
        row: HotkeyRowDefinition,
        binding: HotkeyBinding,
        otherId: String,
        rows: [HotkeyRowDefinition]
    ) -> HotkeyConflict {
        let otherTitle = rows.first { $0.id == otherId }?.title ?? "another Basil shortcut"
        return HotkeyConflict(
            hotkeyId: row.id,
            kind: .basilDuplicate,
            source: otherTitle,
            certainty: .exact,
            message: "\(row.title) (\(binding.displayString)) uses the same keys as \(otherTitle). Only one of them can use these keys, so choose another shortcut for this one."
        )
    }
}
