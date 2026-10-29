import Foundation

@MainActor
protocol ReactSkillsSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: ReasoningSettingsViewModel)
    func sendSnapshot(viewModel: ReasoningSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
}

extension ReactSkillsSettingsWebView: ReactSkillsSettingsBridgeOutput {
    func sendInit(viewModel: ReasoningSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilSkillsSettings && window.basilSkillsSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: ReasoningSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilSkillsSettings && window.basilSkillsSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilSkillsSettings && window.basilSkillsSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: ReasoningSettingsViewModel) -> [String: Any] {
        var event = SkillsSettingsPayloadBuilder.makeSnapshotPayload(viewModel: viewModel)
        event["type"] = type
        return event
    }
}
