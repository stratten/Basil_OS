import Foundation

@MainActor
protocol ReactMeetingDetectionSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: MeetingDetectionSettingsViewModel)
    func sendSnapshot(viewModel: MeetingDetectionSettingsViewModel)
    func sendAvailableApps()
    func sendAppSearchResults(requestId: String, apps: [[String: Any]])
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactMeetingDetectionSettingsWebView: ReactMeetingDetectionSettingsBridgeOutput {
    func sendInit(viewModel: MeetingDetectionSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        event["availableApps"] = MeetingDetectionSettingsPayloadBuilder.makeAvailableAppsPayload()
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: MeetingDetectionSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    func sendAvailableApps() {
        let event: [String: Any] = [
            "type": "availableApps",
            "availableApps": MeetingDetectionSettingsPayloadBuilder.makeAvailableAppsPayload(),
        ]
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    func sendAppSearchResults(requestId: String, apps: [[String: Any]]) {
        let event: [String: Any] = ["type": "searchAppsResults", "requestId": requestId, "apps": apps]
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilMeetingDetectionSettings && window.basilMeetingDetectionSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: MeetingDetectionSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "settings": MeetingDetectionSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel),
            "excludedApps": MeetingDetectionSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel),
            "requiredBundleIds": MeetingDetectionSettingsPayloadBuilder.requiredBundleIds,
        ]
    }
}
