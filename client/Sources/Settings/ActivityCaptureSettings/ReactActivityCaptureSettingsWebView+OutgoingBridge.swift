import Foundation

@MainActor
protocol ReactActivityCaptureSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: ActivityCaptureSettingsViewModel)
    func sendSnapshot(viewModel: ActivityCaptureSettingsViewModel)
    func sendStatus(viewModel: ActivityCaptureSettingsViewModel)
    func sendProgress(viewModel: ActivityCaptureSettingsViewModel, requestId: String?)
    func sendAvailableApps()
    func sendAppSearchResults(requestId: String, apps: [[String: Any]])
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactActivityCaptureSettingsWebView: ReactActivityCaptureSettingsBridgeOutput {
    func sendInit(viewModel: ActivityCaptureSettingsViewModel) {
        var event: [String: Any] = [
            "type": "init",
            "protocolVersion": 1,
            "settings": ActivityCaptureSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel),
            "status": ActivityCaptureSettingsPayloadBuilder.makeStatusPayload(viewModel: viewModel),
            "processingProgress": ActivityCaptureSettingsPayloadBuilder.makeProcessingProgressPayload(viewModel: viewModel),
            "availableModels": ActivityCaptureSettingsPayloadBuilder.makeModelsPayload(viewModel: viewModel),
            "availableApps": ActivityCaptureSettingsPayloadBuilder.makeAvailableAppsPayload(),
            "excludedApps": ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel),
            "retentionDayOptions": viewModel.retentionDayOptions,
            "maxStorageOptions": viewModel.maxStorageOptions,
        ]
        if let stats = ActivityCaptureSettingsPayloadBuilder.makeStatsPayload(viewModel: viewModel) {
            event["stats"] = stats
        } else {
            event["stats"] = NSNull()
        }
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: ActivityCaptureSettingsViewModel) {
        var event: [String: Any] = [
            "type": "snapshot",
            "settings": ActivityCaptureSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel),
            "availableModels": ActivityCaptureSettingsPayloadBuilder.makeModelsPayload(viewModel: viewModel),
            "excludedApps": ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel),
        ]
        if let stats = ActivityCaptureSettingsPayloadBuilder.makeStatsPayload(viewModel: viewModel) {
            event["stats"] = stats
        } else {
            event["stats"] = NSNull()
        }
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendStatus(viewModel: ActivityCaptureSettingsViewModel) {
        let event: [String: Any] = [
            "type": "status",
            "status": ActivityCaptureSettingsPayloadBuilder.makeStatusPayload(viewModel: viewModel),
        ]
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendProgress(viewModel: ActivityCaptureSettingsViewModel, requestId: String?) {
        var event: [String: Any] = [
            "type": "progress",
            "processingProgress": ActivityCaptureSettingsPayloadBuilder.makeProcessingProgressPayload(viewModel: viewModel),
        ]
        if let requestId {
            event["requestId"] = requestId
        }
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendAvailableApps() {
        let event: [String: Any] = [
            "type": "availableApps",
            "availableApps": ActivityCaptureSettingsPayloadBuilder.makeAvailableAppsPayload(),
        ]
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendAppSearchResults(requestId: String, apps: [[String: Any]]) {
        let event: [String: Any] = [
            "type": "searchAppsResults",
            "requestId": requestId,
            "apps": apps,
        ]
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilActivityCaptureSettings && window.basilActivityCaptureSettings.onEvent", args: event)
    }
}
