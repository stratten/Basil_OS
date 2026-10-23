import Foundation

/// A single row in the Hotkeys settings tab: one backend hotkey id paired
/// with the title/subtitle shown to the user. Shared by the legacy SwiftUI
/// `HotkeySettingsViewModel` and the React bridge controller so there is
/// exactly one source of row ids/labels, not two copies that can drift.
struct HotkeyRowDefinition {
    let id: String
    let title: String
    let subtitle: String?

    init(id: String, title: String, subtitle: String? = nil) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
    }
}

/// Central catalog of the hotkey rows exposed in Settings. This intentionally
/// only lists the 5 rows shown in the UI, not all 8 backend keys in
/// `HotkeySettings` -- `capture_screen`, `streaming_transcription`, and
/// `insert_assistant_output` are carried through on every save without ever
/// being surfaced as editable rows, matching the pre-existing SwiftUI tab.
enum HotkeyRowCatalog {
    // `get_suggestions` (legacy F9) and `enhanced_suggestions` (legacy F10)
    // were removed during the AssistantSession unification -- both
    // modalities now live behind `assistantSession` with an in-widget
    // speak/type toggle. Other commented-out ids are pre-AssistantSession
    // legacy holdovers also no longer surfaced in settings.
    static let rows: [HotkeyRowDefinition] = [
        HotkeyRowDefinition(id: "transcribe_audio", title: "Transcribe Audio"),
        HotkeyRowDefinition(id: "conversation_toggle", title: "Toggle Conversation"),
        HotkeyRowDefinition(
            id: "assistant_session",
            title: BasilTeamIdentity.assistantSession.displayName,
            subtitle: BasilTeamIdentity.assistantSession.descriptor
        ),
        HotkeyRowDefinition(
            id: "agent_task",
            title: BasilTeamIdentity.agentTask.displayName,
            subtitle: BasilTeamIdentity.agentTask.descriptor
        ),
        HotkeyRowDefinition(
            id: "home_board_toggle",
            title: "Open Basil Home",
            subtitle: "Show or hide the Basil Home board"
        ),
    ]

    static func defaultBinding(for id: String) -> HotkeyBinding {
        switch id {
        case "transcribe_audio":
            return HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: "command")
        case "conversation_toggle":
            return HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        case "assistant_session":
            return HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: "option")
        case "agent_task":
            return HotkeyBinding(key: "Space", enabled: true, modifiers: ["option"])
        case "home_board_toggle":
            return HotkeyBinding(key: "B", enabled: true, modifiers: ["control", "option"])
        default:
            return HotkeyBinding(key: "", enabled: false, modifiers: [])
        }
    }
}
