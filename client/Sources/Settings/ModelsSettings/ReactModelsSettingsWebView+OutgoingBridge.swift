import Foundation

@MainActor
protocol ReactModelsSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: ModelDownloadViewModel)
    func sendSnapshot(viewModel: ModelDownloadViewModel)
    func sendDownloadLogLine(modelId: String, message: String)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactModelsSettingsWebView: ReactModelsSettingsBridgeOutput {
    func sendInit(viewModel: ModelDownloadViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilModelsSettings && window.basilModelsSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: ModelDownloadViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilModelsSettings && window.basilModelsSettings.onEvent", args: event)
    }

    func sendDownloadLogLine(modelId: String, message: String) {
        let event: [String: Any] = [
            "type": "downloadLogLine",
            "modelId": modelId,
            "message": message,
        ]
        callJS("window.basilModelsSettings && window.basilModelsSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = [
            "type": "intentResult",
            "requestId": requestId,
            "status": status,
        ]
        if let message {
            event["message"] = message
        }
        callJS("window.basilModelsSettings && window.basilModelsSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilModelsSettings && window.basilModelsSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: ModelDownloadViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoadingModels": !viewModel.isLoaded,
            "localVisionFallbackEnabled": viewModel.localVisionFallbackEnabled,
            "isLocalVisionFallbackModelInstalled": viewModel.isLocalVisionFallbackModelInstalled,
            "reasoningFallbackEnabled": viewModel.reasoningFallbackEnabled,
            "reasoningFallbackModelId": viewModel.reasoningFallbackModelId,
            "reasoningGroups": ModelsSettingsPayloadBuilder.makeCapabilityGroups(
                modelGroups: viewModel.modelGroups,
                capability: .reasoning,
                downloadProgress: viewModel.downloadProgress,
                downloadProgressMetadata: viewModel.downloadProgressMetadata
            ),
            "transcriptionGroups": ModelsSettingsPayloadBuilder.makeCapabilityGroups(
                modelGroups: viewModel.modelGroups,
                capability: .transcription,
                downloadProgress: viewModel.downloadProgress,
                downloadProgressMetadata: viewModel.downloadProgressMetadata
            ),
        ]
    }
}
