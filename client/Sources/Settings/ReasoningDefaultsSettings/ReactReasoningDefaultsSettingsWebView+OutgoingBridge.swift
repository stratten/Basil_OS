import Foundation

@MainActor
protocol ReactReasoningDefaultsSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: ReasoningSettingsViewModel)
    func sendSnapshot(viewModel: ReasoningSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactReasoningDefaultsSettingsWebView: ReactReasoningDefaultsSettingsBridgeOutput {
    func sendInit(viewModel: ReasoningSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilReasoningDefaultsSettings && window.basilReasoningDefaultsSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: ReasoningSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilReasoningDefaultsSettings && window.basilReasoningDefaultsSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilReasoningDefaultsSettings && window.basilReasoningDefaultsSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilReasoningDefaultsSettings && window.basilReasoningDefaultsSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: ReasoningSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "settings": ReasoningDefaultsSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel),
        ]
    }
}
