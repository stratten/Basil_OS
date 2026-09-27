import Foundation

@MainActor
protocol ReactProactiveSuggestionsSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: AmbientSuggestionSettingsViewModel)
    func sendSnapshot(viewModel: AmbientSuggestionSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactProactiveSuggestionsSettingsWebView: ReactProactiveSuggestionsSettingsBridgeOutput {
    func sendInit(viewModel: AmbientSuggestionSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilProactiveSuggestionsSettings && window.basilProactiveSuggestionsSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: AmbientSuggestionSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilProactiveSuggestionsSettings && window.basilProactiveSuggestionsSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilProactiveSuggestionsSettings && window.basilProactiveSuggestionsSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilProactiveSuggestionsSettings && window.basilProactiveSuggestionsSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: AmbientSuggestionSettingsViewModel) -> [String: Any] {
        var event: [String: Any] = ["type": type, "isLoading": viewModel.isLoading]
        if !viewModel.isLoading {
            event["settings"] = ProactiveSuggestionsSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel)
        }
        return event
    }
}
