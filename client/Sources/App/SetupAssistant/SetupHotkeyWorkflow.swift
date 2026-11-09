import Foundation

/// Where the setup flow reads and saves the person's hotkeys. The live store is the same backend route the Settings Hotkeys page uses, and tests pass a fake.
@MainActor
protocol SetupHotkeyStoring {
    func load() async throws -> [String: HotkeyBinding]
    func save(_ bindings: [String: HotkeyBinding]) async throws
}

@MainActor
struct LiveSetupHotkeyStore: SetupHotkeyStoring {
    nonisolated init() {}

    func load() async throws -> [String: HotkeyBinding] {
        let data = try await APIClient.shared.get("/settings/hotkeys")
        // No key conversion: HotkeyBinding has explicit coding keys, as in the Settings Hotkeys page.
        return try JSONDecoder().decode(HotkeySettingsResponse.self, from: data).settings
    }

    func save(_ bindings: [String: HotkeyBinding]) async throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        _ = try await APIClient.shared.put("/settings/hotkeys", data: try encoder.encode(bindings))
        await HotkeyService.shared.refreshHotkeys()
    }
}

struct SetupHotkeyChange {
    let id: String
    let title: String
    let from: HotkeyBinding
    let to: HotkeyBinding
    /// What the old keys clashed with, for example "this Mac's media keys".
    let reason: String
}

struct SetupHotkeyUnresolved {
    let id: String
    let title: String
    let message: String
}

struct SetupHotkeyApplyOutcome {
    let saved: Bool
    let conflicts: [HotkeyConflict]
    let rows: [[String: Any]]

    var payload: [String: Any] {
        ["saved": saved, "conflicts": conflicts.map(\.payload), "rows": rows]
    }
}

struct SetupHotkeyResolveOutcome {
    let changes: [SetupHotkeyChange]
    let unresolved: [SetupHotkeyUnresolved]

    var payload: [String: Any] {
        [
            "changes": changes.map { change -> [String: Any] in
                [
                    "id": change.id,
                    "title": change.title,
                    "from": SetupHotkeyPayload.binding(change.from),
                    "to": SetupHotkeyPayload.binding(change.to),
                    "reason": change.reason,
                ]
            },
            "unresolved": unresolved.map { item -> [String: Any] in
                ["id": item.id, "title": item.title, "message": item.message]
            },
        ]
    }
}

/// The three things the setup page can ask about hotkeys: check them, save one, or fix every clash. It owns the decisions, so a stale page can never save a clash by accident.
@MainActor
struct SetupHotkeyWorkflow {
    let store: SetupHotkeyStoring
    let rows: [HotkeyRowDefinition]
    let readSystemState: () -> HotkeySystemState

    init(
        store: SetupHotkeyStoring = LiveSetupHotkeyStore(),
        rows: [HotkeyRowDefinition] = HotkeyRowCatalog.rows,
        readSystemState: @escaping () -> HotkeySystemState = { HotkeyConflictEvaluator.readSystemState() }
    ) {
        self.store = store
        self.rows = rows
        self.readSystemState = readSystemState
    }

    func evaluate() async throws -> [String: Any] {
        let bindings = try await currentBindings()
        return ["rows": SetupHotkeyPayload.rows(bindings: bindings, rows: rows, system: readSystemState())]
    }

    /// Saves the keys for one row. Keys that clash are not saved unless the person has been told and acknowledged. With `checkOnly`, nothing is saved: `saved` then means the keys would be accepted, so the confirm screen can hold a choice until the person presses Do it.
    func apply(id: String, requested: HotkeySettingsBindingPayload, acknowledgeConflict: Bool, checkOnly: Bool = false) async throws -> SetupHotkeyApplyOutcome {
        guard rows.contains(where: { $0.id == id }) else { throw SetupHotkeyError.unknownHotkey }
        var bindings = try await currentBindings()
        guard let existing = bindings[id] else { throw SetupHotkeyError.unknownHotkey }
        let binding = HotkeyBinding(
            key: requested.key,
            enabled: true,
            modifiers: requested.modifiers,
            hotkeyDescription: existing.hotkeyDescription,
            isDoublePress: requested.isDoublePress,
            doublePressKey: requested.doublePressKey
        )
        try SetupHotkeyPayload.validate(binding)

        let system = readSystemState()
        let conflicts = HotkeyConflictEvaluator.conflicts(replacing: id, with: binding, in: bindings, rows: rows, system: system)
        if !conflicts.isEmpty && !acknowledgeConflict {
            return SetupHotkeyApplyOutcome(
                saved: false,
                conflicts: conflicts,
                rows: SetupHotkeyPayload.rows(bindings: bindings, rows: rows, system: system)
            )
        }

        bindings[id] = binding
        if !checkOnly {
            try await store.save(bindings)
        }
        return SetupHotkeyApplyOutcome(
            saved: true,
            conflicts: [],
            rows: SetupHotkeyPayload.rows(bindings: bindings, rows: rows, system: system)
        )
    }

    /// Switches every clashing row that has a safe replacement, in one save. Rows with no safe replacement are reported and left alone. Rows in `excluding` are the ones the person already decided on, so they are never switched here. Nothing is saved when there is no clash.
    func resolveConflicts(excluding excludedIds: Set<String> = []) async throws -> SetupHotkeyResolveOutcome {
        let bindings = try await currentBindings()
        let system = readSystemState()
        let conflicts = HotkeyConflictEvaluator.conflicts(bindings: bindings, rows: rows, system: system)
        let conflictedIds = rows.map(\.id).filter { id in
            !excludedIds.contains(id) && conflicts.contains { $0.hotkeyId == id }
        }
        let alternatives = HotkeyAlternativeResolver.alternatives(for: conflictedIds, bindings: bindings, rows: rows, system: system)

        var updated = bindings
        var changes: [SetupHotkeyChange] = []
        var unresolved: [SetupHotkeyUnresolved] = []
        for row in rows where conflictedIds.contains(row.id) {
            let firstConflict = conflicts.first { $0.hotkeyId == row.id }
            guard let replacement = alternatives[row.id], let current = bindings[row.id] else {
                unresolved.append(SetupHotkeyUnresolved(id: row.id, title: row.title, message: firstConflict?.message ?? ""))
                continue
            }
            updated[row.id] = HotkeyBinding(
                key: replacement.key,
                enabled: true,
                modifiers: replacement.modifiers,
                hotkeyDescription: current.hotkeyDescription,
                isDoublePress: replacement.isDoublePress,
                doublePressKey: replacement.doublePressKey
            )
            changes.append(SetupHotkeyChange(
                id: row.id,
                title: row.title,
                from: current,
                to: replacement,
                reason: firstConflict?.source ?? "another shortcut"
            ))
        }

        if !changes.isEmpty {
            try await store.save(updated)
        }
        return SetupHotkeyResolveOutcome(changes: changes, unresolved: unresolved)
    }

    private func currentBindings() async throws -> [String: HotkeyBinding] {
        let loaded = try await store.load()
        guard !loaded.isEmpty else { throw SetupHotkeyError.notLoaded }
        return loaded
    }
}
