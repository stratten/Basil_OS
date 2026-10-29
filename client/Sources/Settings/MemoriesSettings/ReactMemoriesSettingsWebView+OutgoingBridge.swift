import Foundation

extension ReactMemoriesSettingsWebView {
    func sendInit(
        settings: ZettelSettingsData,
        stats: ZettelStatsData?,
        narrativeProgress: NarrativeProgressData?,
        availableModels: [ActivityCaptureModelInfo]
    ) {
        callJS("window.basilMemoriesSettings.onEvent", args: [
            "type": "init",
            "protocolVersion": 1,
            "settings": MemoriesSettingsPayloadBuilder.settingsPayload(settings),
            "stats": MemoriesSettingsPayloadBuilder.statsPayload(stats),
            "narrativeProgress": MemoriesSettingsPayloadBuilder.narrativeProgressPayload(narrativeProgress),
            "availableModels": MemoriesSettingsPayloadBuilder.modelsPayload(availableModels),
        ])
    }

    func sendSnapshot(
        settings: ZettelSettingsData,
        stats: ZettelStatsData?,
        availableModels: [ActivityCaptureModelInfo]
    ) {
        callJS("window.basilMemoriesSettings.onEvent", args: [
            "type": "snapshot",
            "settings": MemoriesSettingsPayloadBuilder.settingsPayload(settings),
            "stats": MemoriesSettingsPayloadBuilder.statsPayload(stats),
            "availableModels": MemoriesSettingsPayloadBuilder.modelsPayload(availableModels),
        ])
    }

    func sendProgress(requestId: String, progress: NarrativeProgressData) {
        callJS("window.basilMemoriesSettings.onEvent", args: [
            "type": "progress",
            "requestId": requestId,
            "narrativeProgress": MemoriesSettingsPayloadBuilder.narrativeProgressPayload(progress),
        ])
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        callJS("window.basilMemoriesSettings.onEvent", args: [
            "type": "intentResult",
            "requestId": requestId,
            "status": status,
            "message": message ?? NSNull(),
        ] as [String: Any])
    }

    func sendLoadError(message: String) {
        callJS("window.basilMemoriesSettings.onEvent", args: [
            "type": "loadError",
            "message": message,
        ])
    }
}
