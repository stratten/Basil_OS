import Foundation

@MainActor
protocol ReactCustomModelsBridgeOutput: AnyObject {
    func sendInit(viewModel: CustomModelsViewModel)
    func sendSnapshot(viewModel: CustomModelsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
    func sendHFProbeResult(requestId: String, response: HFProbeResponse)
    func sendGGUFMetadataResult(requestId: String, response: GGUFMetadataResponse?)
    func sendLocalFilePicked(requestId: String, path: String)
    func sendLocalFilePickError(requestId: String, message: String)
    func sendConnectionTestResult(requestId: String, success: Bool, message: String)
    func sendDownloadProgress(modelId: String, progress: Double, status: String)
}

extension ReactCustomModelsWebView: ReactCustomModelsBridgeOutput {
    func sendInit(viewModel: CustomModelsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendSnapshot(viewModel: CustomModelsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendHFProbeResult(requestId: String, response: HFProbeResponse) {
        let event: [String: Any] = [
            "type": "hfProbeResult",
            "requestId": requestId,
            "repoId": response.repoId,
            "ggufFiles": response.ggufFiles.map { file -> [String: Any] in
                ["name": file.name, "sizeBytes": file.sizeBytes as Any? ?? NSNull(), "sizeHuman": file.sizeHuman as Any? ?? NSNull()]
            },
            "modelMetadata": response.modelMetadata.map { metadata -> [String: Any] in
                [
                    "contextWindow": metadata.contextWindow as Any? ?? NSNull(),
                    "modelType": metadata.modelType as Any? ?? NSNull(),
                    "architecture": metadata.architecture as Any? ?? NSNull(),
                ]
            } as Any? ?? NSNull(),
            "error": response.error as Any? ?? NSNull(),
        ]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendGGUFMetadataResult(requestId: String, response: GGUFMetadataResponse?) {
        let event: [String: Any] = [
            "type": "ggufMetadataResult",
            "requestId": requestId,
            "success": response?.success ?? false,
            "contextWindow": response?.contextWindow as Any? ?? NSNull(),
            "architecture": response?.architecture as Any? ?? NSNull(),
            "modelName": response?.modelName as Any? ?? NSNull(),
            "error": response?.error as Any? ?? NSNull(),
        ]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendLocalFilePicked(requestId: String, path: String) {
        let event: [String: Any] = ["type": "localFilePicked", "requestId": requestId, "path": path]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendLocalFilePickError(requestId: String, message: String) {
        let event: [String: Any] = ["type": "localFilePickError", "requestId": requestId, "message": message]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendConnectionTestResult(requestId: String, success: Bool, message: String) {
        let event: [String: Any] = [
            "type": "connectionTestResult", "requestId": requestId, "success": success, "message": message,
        ]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    func sendDownloadProgress(modelId: String, progress: Double, status: String) {
        let event: [String: Any] = [
            "type": "downloadProgress", "modelId": modelId, "progress": progress, "status": status,
        ]
        callJS("window.basilCustomModels && window.basilCustomModels.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: CustomModelsViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "models": CustomModelsPayloadBuilder.makeModelSummaries(
                models: viewModel.customModels,
                downloadProgressMap: viewModel.downloadProgressMap,
                downloadStatus: viewModel.downloadStatus
            ),
        ]
    }
}
