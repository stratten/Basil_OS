import Foundation

// MARK: - AgentTask Settings Models

struct AgentTaskSettingsResponse: Codable {
    let status: String
    let settings: AgentTaskSettings
}

/// Default input modality for agentTask captures.
///
/// Mirrors the backend `Literal["voice", "text"]` field on `AgentTaskPreferences`.
/// Decoded defensively from the raw string so unknown future values fall back to `.voice`.
enum AgentTaskInputModality: String, Codable, CaseIterable, Equatable {
    case voice
    case text

    /// Defensive parser used when reading from the cached settings struct's raw string.
    static func from(_ raw: String?) -> AgentTaskInputModality {
        guard let raw = raw?.lowercased() else { return .voice }
        return AgentTaskInputModality(rawValue: raw) ?? .voice
    }
}

struct AgentTaskSettings: Codable {
    let widgetPosition: WidgetPosition?     // X, Y, screenID - applies to all phases
    let resultWidgetSize: WidgetSize?      // Width, height - only for result widget (capture is fixed 140x140)
    let enablePushToTalk: Bool
    let pushToTalkThresholdMs: Int
    /// Raw backend string ("voice" or "text"). Use `modality` for a typed accessor.
    let defaultInputModality: String
    let autoReopenOnCompletion: Bool

    enum CodingKeys: String, CodingKey {
        case widgetPosition = "widget_position"
        case resultWidgetSize = "result_widget_size"
        case enablePushToTalk = "enable_push_to_talk"
        case pushToTalkThresholdMs = "push_to_talk_threshold_ms"
        case defaultInputModality = "default_input_modality"
        case autoReopenOnCompletion = "auto_reopen_on_completion"
    }

    /// Typed accessor for the default input modality. Falls back to `.voice` for missing
    /// or unrecognized raw values so older cached payloads stay forward-compatible.
    var modality: AgentTaskInputModality {
        AgentTaskInputModality.from(defaultInputModality)
    }

    init(
        widgetPosition: WidgetPosition?,
        resultWidgetSize: WidgetSize?,
        enablePushToTalk: Bool,
        pushToTalkThresholdMs: Int,
        defaultInputModality: String,
        autoReopenOnCompletion: Bool = true
    ) {
        self.widgetPosition = widgetPosition
        self.resultWidgetSize = resultWidgetSize
        self.enablePushToTalk = enablePushToTalk
        self.pushToTalkThresholdMs = pushToTalkThresholdMs
        self.defaultInputModality = defaultInputModality
        self.autoReopenOnCompletion = autoReopenOnCompletion
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.widgetPosition = try container.decodeIfPresent(WidgetPosition.self, forKey: .widgetPosition)
        self.resultWidgetSize = try container.decodeIfPresent(WidgetSize.self, forKey: .resultWidgetSize)
        self.enablePushToTalk = try container.decodeIfPresent(Bool.self, forKey: .enablePushToTalk) ?? false
        self.pushToTalkThresholdMs = try container.decodeIfPresent(Int.self, forKey: .pushToTalkThresholdMs) ?? 750
        self.defaultInputModality = try container.decodeIfPresent(String.self, forKey: .defaultInputModality) ?? "voice"
        self.autoReopenOnCompletion = try container.decodeIfPresent(Bool.self, forKey: .autoReopenOnCompletion) ?? true
    }
}
