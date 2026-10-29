import Foundation

@MainActor
protocol ReactReasoningAPIModelsBridgeOutput: AnyObject {
    func sendInit(viewModel: APIModelsViewModel)
    func sendSnapshot(viewModel: APIModelsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactReasoningAPIModelsWebView: ReactReasoningAPIModelsBridgeOutput {
    func sendInit(viewModel: APIModelsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilReasoningApiModels && window.basilReasoningApiModels.onEvent", args: event)
    }

    func sendSnapshot(viewModel: APIModelsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilReasoningApiModels && window.basilReasoningApiModels.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilReasoningApiModels && window.basilReasoningApiModels.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilReasoningApiModels && window.basilReasoningApiModels.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: APIModelsViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "useApiModels": viewModel.apiSettings.useApiModels,
            "providers": ReasoningApiModelsPayloadBuilder.makeProviderSummaries(providers: viewModel.apiProviders),
        ]
    }
}
