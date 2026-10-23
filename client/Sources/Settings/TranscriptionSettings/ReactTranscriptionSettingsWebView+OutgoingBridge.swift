import Foundation

@MainActor
protocol ReactTranscriptionSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: TranscriptionSettingsViewModel)
    func sendSnapshot(viewModel: TranscriptionSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactTranscriptionSettingsWebView: ReactTranscriptionSettingsBridgeOutput {
    func sendInit(viewModel: TranscriptionSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        event["unloadDelayOptions"] = Self.unloadDelayOptions
        callJS("window.basilTranscriptionSettings && window.basilTranscriptionSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: TranscriptionSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilTranscriptionSettings && window.basilTranscriptionSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilTranscriptionSettings && window.basilTranscriptionSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilTranscriptionSettings && window.basilTranscriptionSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: TranscriptionSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "settings": [
                "selectedModel": viewModel.selectedModel,
                "apiModels": viewModel.apiModels.map(Self.modelOptionPayload),
                "localModels": viewModel.localModels.map(Self.modelOptionPayload),
                "unloadDelaySeconds": viewModel.selectedUnloadDelay.rawValue,
                "autoPasteTranscription": viewModel.autoPasteTranscription,
                "autoCloseOnPaste": viewModel.autoCloseOnPaste,
                "startMeetingDetectionAtStartup": viewModel.startMeetingDetectionAtStartup,
                "enablePushToTalk": viewModel.enablePushToTalk,
                "pushToTalkThresholdMs": viewModel.pushToTalkThresholdMs,
                "textReplacements": viewModel.textReplacements.map(
                    Self.textReplacementPayload
                ),
            ],
        ]
    }

    private static func textReplacementPayload(
        _ rule: TranscriptionTextReplacementRule
    ) -> [String: Any] {
        [
            "source": rule.source,
            "replacement": rule.replacement,
        ]
    }

    private static func modelOptionPayload(_ model: TranscriptionModelOption) -> [String: Any] {
        [
            "id": model.id,
            "displayName": model.displayName,
            "isApiModel": model.isApiModel,
            "provider": model.provider as Any? ?? NSNull(),
        ]
    }

    /// Mirrors `TranscriptionModelUnloadDelay.allCases` -- sent once in
    /// `init` since this fixed list never changes at runtime, matching how
    /// Meeting Automation sends its static `analysisModeOptions` list.
    private static let unloadDelayOptions: [[String: Any]] = TranscriptionModelUnloadDelay.allCases.map {
        ["seconds": $0.rawValue, "label": $0.displayName]
    }
}
