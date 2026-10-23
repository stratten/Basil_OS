// MARK: - Model Types
enum TranscriptionModelUnloadDelay: Int, Codable, CaseIterable {
    case immediately = 0
    case seconds5 = 5
    case seconds30 = 30
    case minutes1 = 60
    case minutes2 = 120
    case minutes5 = 300
    case minutes10 = 600
    case minutes30 = 1800
    case hours1 = 3600
    
    var displayName: String {
        switch self {
        case .immediately: return "Immediately"
        case .seconds5: return "5 seconds"
        case .seconds30: return "30 seconds"
        case .minutes1: return "1 minute"
        case .minutes2: return "2 minutes"
        case .minutes5: return "5 minutes"
        case .minutes10: return "10 minutes"
        case .minutes30: return "30 minutes"
        case .hours1: return "1 hour"
        }
    }
}

// MARK: - Transcription History Item View
struct UIPreferencesResponse: Codable {
    let status: String
    let settings: UIPreferences
}

struct UIPreferences: Codable {
    let transcription: TranscriptionPreferences
    let suggestionWidgetPosition: String?
    let suggestionWidgetSize: [Int]?
    let visionModel: String?
    let languageModel: String?
    let reasoningModel: String?
}

struct TranscriptionPreferences: Codable {
    let transcriptionModelUnloadDelay: Int
    let autoPasteTranscription: Bool
    let autoCloseOnPaste: Bool
    let language: String
    
    enum CodingKeys: String, CodingKey {
        case transcriptionModelUnloadDelay = "model_unload_delay"
        case autoPasteTranscription = "auto_paste_transcription"
        case autoCloseOnPaste = "auto_close_on_paste"
        case language
    }
}

struct TranscriptionSettingsResponse: Codable {
    let status: String
    let settings: TranscriptionSettings
}

struct TranscriptionSettings: Codable {
    let modelUnloadDelay: Int
    let autoPaste: Bool
    let autoCloseOnPaste: Bool
    let language: String
    let selectedModel: String
    let widgetSize: WidgetSize?
    let widgetPosition: WidgetPosition?
    let isWidgetMinimized: Bool
    let enablePushToTalk: Bool
    let pushToTalkThresholdMs: Int
    // Meeting post-processing automation defaults. Declared as `var` with
    // defaults so the synthesized memberwise initializer keeps them omittable
    // (existing call sites that don't set them still compile).
    var autoRetranscribeOnStop: Bool = false
    var autoRetranscribeDuringRecording: Bool = false
    var retranscribeWindowSeconds: Int = 600
    var autoAnalyzeOnComplete: Bool = false
    var autoAnalyzeModes: [String] = []
    var autoAnalyzeCustomInstructions: String = ""
    var autoAnalyzeTiming: String = "after"
    var liveTranscriptionByDefault: Bool = true
    var textReplacements: [TranscriptionTextReplacementRule] = []

    enum CodingKeys: String, CodingKey {
        case modelUnloadDelay = "model_unload_delay"
        case autoPaste = "auto_paste"
        case autoCloseOnPaste = "auto_close_on_paste"
        case language
        case selectedModel = "selected_model"
        case widgetSize = "widget_size"
        case widgetPosition = "widget_position"
        case isWidgetMinimized = "is_widget_minimized"
        case enablePushToTalk = "enable_push_to_talk"
        case pushToTalkThresholdMs = "push_to_talk_threshold_ms"
        case autoRetranscribeOnStop = "auto_retranscribe_on_stop"
        case autoRetranscribeDuringRecording = "auto_retranscribe_during_recording"
        case retranscribeWindowSeconds = "retranscribe_window_seconds"
        case autoAnalyzeOnComplete = "auto_analyze_on_complete"
        case autoAnalyzeModes = "auto_analyze_modes"
        case autoAnalyzeCustomInstructions = "auto_analyze_custom_instructions"
        case autoAnalyzeTiming = "auto_analyze_timing"
        case liveTranscriptionByDefault = "live_transcription_by_default"
        case textReplacements = "text_replacements"
    }
}

extension TranscriptionSettings {
    /// Defensive decoder: the automation fields are decoded with `decodeIfPresent`
    /// so a stale cached payload (written before these fields existed) still
    /// decodes, falling back to behavior-preserving defaults. The custom
    /// initializer lives in an extension so the synthesized memberwise
    /// initializer remains available to existing call sites.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        modelUnloadDelay = try container.decode(Int.self, forKey: .modelUnloadDelay)
        autoPaste = try container.decode(Bool.self, forKey: .autoPaste)
        autoCloseOnPaste = try container.decode(Bool.self, forKey: .autoCloseOnPaste)
        language = try container.decode(String.self, forKey: .language)
        selectedModel = try container.decode(String.self, forKey: .selectedModel)
        widgetSize = try container.decodeIfPresent(WidgetSize.self, forKey: .widgetSize)
        widgetPosition = try container.decodeIfPresent(WidgetPosition.self, forKey: .widgetPosition)
        isWidgetMinimized = try container.decode(Bool.self, forKey: .isWidgetMinimized)
        enablePushToTalk = try container.decode(Bool.self, forKey: .enablePushToTalk)
        pushToTalkThresholdMs = try container.decode(Int.self, forKey: .pushToTalkThresholdMs)
        autoRetranscribeOnStop = try container.decodeIfPresent(Bool.self, forKey: .autoRetranscribeOnStop) ?? false
        autoRetranscribeDuringRecording = try container.decodeIfPresent(Bool.self, forKey: .autoRetranscribeDuringRecording) ?? false
        retranscribeWindowSeconds = try container.decodeIfPresent(Int.self, forKey: .retranscribeWindowSeconds) ?? 600
        autoAnalyzeOnComplete = try container.decodeIfPresent(Bool.self, forKey: .autoAnalyzeOnComplete) ?? false
        autoAnalyzeModes = try container.decodeIfPresent([String].self, forKey: .autoAnalyzeModes) ?? []
        autoAnalyzeCustomInstructions = try container.decodeIfPresent(String.self, forKey: .autoAnalyzeCustomInstructions) ?? ""
        autoAnalyzeTiming = try container.decodeIfPresent(String.self, forKey: .autoAnalyzeTiming) ?? "after"
        liveTranscriptionByDefault = try container.decodeIfPresent(Bool.self, forKey: .liveTranscriptionByDefault) ?? true
        textReplacements = try container.decodeIfPresent([TranscriptionTextReplacementRule].self, forKey: .textReplacements) ?? []
    }

    /// Returns a copy of the receiver (the last known-good settings, typically
    /// just fetched via GET) with only the given fields overridden. Every
    /// field not passed here is carried over unchanged. Prefer this over
    /// constructing `TranscriptionSettings(...)` directly for a partial
    /// update -- the automation fields carry defaults that silently reset
    /// anything not explicitly threaded through the plain initializer, which
    /// is exactly what caused meeting-automation settings to be wiped by
    /// unrelated widget-geometry/model updates.
    func applying(
        modelUnloadDelay: Int? = nil,
        autoPaste: Bool? = nil,
        autoCloseOnPaste: Bool? = nil,
        language: String? = nil,
        selectedModel: String? = nil,
        widgetSize: WidgetSize? = nil,
        widgetPosition: WidgetPosition? = nil,
        isWidgetMinimized: Bool? = nil,
        enablePushToTalk: Bool? = nil,
        pushToTalkThresholdMs: Int? = nil,
        autoRetranscribeOnStop: Bool? = nil,
        autoRetranscribeDuringRecording: Bool? = nil,
        retranscribeWindowSeconds: Int? = nil,
        autoAnalyzeOnComplete: Bool? = nil,
        autoAnalyzeModes: [String]? = nil,
        autoAnalyzeCustomInstructions: String? = nil,
        autoAnalyzeTiming: String? = nil,
        liveTranscriptionByDefault: Bool? = nil,
        textReplacements: [TranscriptionTextReplacementRule]? = nil
    ) -> TranscriptionSettings {
        TranscriptionSettings(
            modelUnloadDelay: modelUnloadDelay ?? self.modelUnloadDelay,
            autoPaste: autoPaste ?? self.autoPaste,
            autoCloseOnPaste: autoCloseOnPaste ?? self.autoCloseOnPaste,
            language: language ?? self.language,
            selectedModel: selectedModel ?? self.selectedModel,
            widgetSize: widgetSize ?? self.widgetSize,
            widgetPosition: widgetPosition ?? self.widgetPosition,
            isWidgetMinimized: isWidgetMinimized ?? self.isWidgetMinimized,
            enablePushToTalk: enablePushToTalk ?? self.enablePushToTalk,
            pushToTalkThresholdMs: pushToTalkThresholdMs ?? self.pushToTalkThresholdMs,
            autoRetranscribeOnStop: autoRetranscribeOnStop ?? self.autoRetranscribeOnStop,
            autoRetranscribeDuringRecording: autoRetranscribeDuringRecording ?? self.autoRetranscribeDuringRecording,
            retranscribeWindowSeconds: retranscribeWindowSeconds ?? self.retranscribeWindowSeconds,
            autoAnalyzeOnComplete: autoAnalyzeOnComplete ?? self.autoAnalyzeOnComplete,
            autoAnalyzeModes: autoAnalyzeModes ?? self.autoAnalyzeModes,
            autoAnalyzeCustomInstructions: autoAnalyzeCustomInstructions ?? self.autoAnalyzeCustomInstructions,
            autoAnalyzeTiming: autoAnalyzeTiming ?? self.autoAnalyzeTiming,
            liveTranscriptionByDefault: liveTranscriptionByDefault ?? self.liveTranscriptionByDefault,
            textReplacements: textReplacements ?? self.textReplacements
        )
    }
}
