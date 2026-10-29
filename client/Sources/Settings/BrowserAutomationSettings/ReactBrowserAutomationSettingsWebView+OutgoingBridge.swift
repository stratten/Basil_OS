import Foundation

@MainActor
protocol ReactBrowserAutomationSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: BrowserAutomationSettingsViewModel)
    func sendSnapshot(viewModel: BrowserAutomationSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactBrowserAutomationSettingsWebView: ReactBrowserAutomationSettingsBridgeOutput {
    func sendInit(viewModel: BrowserAutomationSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilBrowserAutomationSettings && window.basilBrowserAutomationSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: BrowserAutomationSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilBrowserAutomationSettings && window.basilBrowserAutomationSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilBrowserAutomationSettings && window.basilBrowserAutomationSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilBrowserAutomationSettings && window.basilBrowserAutomationSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: BrowserAutomationSettingsViewModel) -> [String: Any] {
        var event: [String: Any] = ["type": type, "isLoading": viewModel.isLoading]
        if let settings = viewModel.settings {
            event["settings"] = BrowserAutomationSettingsPayloadBuilder.makeSettingsPayload(settings: settings)
        }
        return event
    }
}
