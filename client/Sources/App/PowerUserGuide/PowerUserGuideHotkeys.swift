import Foundation

/// The hotkeys the capabilities guide names, in the shape its web side reads. The guide shows the user's real bindings, so these come from the saved settings rather than from defaults baked into the guide text.
enum PowerUserGuideHotkeys {
    /// One guide hotkey: the id the web side uses, and the id each source stores the binding under. The hotkey service and the `/settings/hotkeys` response name the same four bindings differently.
    struct Entry: Equatable {
        let guideId: String
        let serviceId: String
        let settingsId: String
    }

    static let entries: [Entry] = [
        Entry(guideId: "transcription", serviceId: "transcribe_audio", settingsId: "transcribe_audio"),
        Entry(guideId: "assistantSession", serviceId: "assistantSession", settingsId: "assistant_session"),
        Entry(guideId: "agentTask", serviceId: "agentTask", settingsId: "agent_task"),
        Entry(guideId: "conversation", serviceId: "conversation_toggle", settingsId: "conversation_toggle"),
    ]

    /// Payload for bindings keyed the way `HotkeyService.hotkeyBindings` keys them.
    static func payload(serviceBindings: [String: HotkeyBinding]) -> [String: Any] {
        payload { serviceBindings[$0.serviceId] }
    }

    /// Payload for bindings keyed the way the `/settings/hotkeys` response keys them.
    static func payload(settingsBindings: [String: HotkeyBinding]) -> [String: Any] {
        payload { settingsBindings[$0.settingsId] }
    }

    /// Reads the saved hotkeys from the backend, which stays correct when global monitoring is off and the service's own copy has not been refreshed.
    @MainActor
    static func fetchPayload(apiClient: APIClient = .shared) async -> [String: Any]? {
        guard let data = try? await apiClient.get("/settings/hotkeys"),
              let response = try? JSONDecoder().decode(HotkeySettingsResponse.self, from: data) else {
            return nil
        }
        return payload(settingsBindings: response.settings)
    }

    private static func payload(_ binding: (Entry) -> HotkeyBinding?) -> [String: Any] {
        var result: [String: Any] = [:]
        for entry in entries {
            guard let binding = binding(entry) else { continue }
            var item: [String: Any] = [
                "display": binding.displayString,
                "enabled": binding.enabled,
                "isDoublePress": binding.isDoublePress,
            ]
            if let doublePressKey = binding.doublePressKey {
                item["doublePressKey"] = doublePressKey
            }
            result[entry.guideId] = item
        }
        return result
    }
}
