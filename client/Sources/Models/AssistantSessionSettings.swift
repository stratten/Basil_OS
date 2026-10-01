import Foundation

// MARK: - AssistantSession Settings Models

struct AssistantSessionSettingsResponse: Codable {
    let status: String
    let settings: AssistantSessionSettings
}

struct AssistantSessionSettings: Codable {
    let enablePushToTalk: Bool
    let pushToTalkThresholdMs: Int
    /// Which entry mode the unified AssistantSession widget opens in by default.
    /// Server contract: "speak" or "type". Required -- there is no longer
    /// a separate hotkey or feature for the typed entry path; the modality
    /// is selected here (and via the in-widget Speak/Type toggle) and
    /// flows through the single `assistantSession` hotkey.
    let defaultInputModality: String

    enum CodingKeys: String, CodingKey {
        case enablePushToTalk = "enable_push_to_talk"
        case pushToTalkThresholdMs = "push_to_talk_threshold_ms"
        case defaultInputModality = "default_input_modality"
    }

    init(
        enablePushToTalk: Bool,
        pushToTalkThresholdMs: Int,
        defaultInputModality: String = "speak"
    ) {
        self.enablePushToTalk = enablePushToTalk
        self.pushToTalkThresholdMs = pushToTalkThresholdMs
        self.defaultInputModality = defaultInputModality
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.enablePushToTalk = try container.decodeIfPresent(Bool.self, forKey: .enablePushToTalk) ?? false
        self.pushToTalkThresholdMs = try container.decodeIfPresent(Int.self, forKey: .pushToTalkThresholdMs) ?? 750
        self.defaultInputModality = try container.decodeIfPresent(String.self, forKey: .defaultInputModality) ?? "speak"
    }

    /// Resolves the wire string into the typed view-model enum. Any
    /// unrecognized value falls back to `.speak` so a malformed string
    /// degrades to the dominant modality rather than crashing the widget.
    var resolvedDefaultInputMode: AssistantSessionInputMode {
        AssistantSessionInputMode(rawValue: defaultInputModality.lowercased()) ?? .speak
    }
}

/// Two entry modalities the unified AssistantSession widget supports. Mirrors the
/// AgentTask widget's voice/text toggle structurally (Bool there, enum here so
/// the wire-string mapping has one named home).
enum AssistantSessionInputMode: String {
    case speak
    case type
}

/// How a refinement started from a history item takes its instruction.
enum AssistantSessionRefinementInput: String {
    case voice
    case typed
}
