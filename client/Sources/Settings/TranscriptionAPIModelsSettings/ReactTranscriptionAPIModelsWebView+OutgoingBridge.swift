import Foundation

@MainActor
protocol ReactTranscriptionAPIModelsBridgeOutput: AnyObject {
    func sendInit(viewModel: TranscriptionAPIModelsViewModel)
    func sendSnapshot(viewModel: TranscriptionAPIModelsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactTranscriptionAPIModelsWebView: ReactTranscriptionAPIModelsBridgeOutput {
    func sendInit(viewModel: TranscriptionAPIModelsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilTranscriptionApiModels && window.basilTranscriptionApiModels.onEvent", args: event)
    }

    func sendSnapshot(viewModel: TranscriptionAPIModelsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilTranscriptionApiModels && window.basilTranscriptionApiModels.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilTranscriptionApiModels && window.basilTranscriptionApiModels.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilTranscriptionApiModels && window.basilTranscriptionApiModels.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: TranscriptionAPIModelsViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "useApiTranscriptionModels": viewModel.useApiTranscriptionModels,
            "openaiEnabled": viewModel.openaiTranscriptionEnabled,
            "openaiHasKey": viewModel.openaiHasKey,
            "models": TranscriptionApiModelsPayloadBuilder.makeModelSummaries(enabledModels: viewModel.models),
        ]
    }
}
