import Foundation

@MainActor
protocol ReactTranscriptionHistoryBridgeOutput: AnyObject {
    func sendInit(viewModel: TranscriptionHistoryViewModel)
    func sendSnapshot(viewModel: TranscriptionHistoryViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactTranscriptionHistoryWebView: ReactTranscriptionHistoryBridgeOutput {
    func sendInit(viewModel: TranscriptionHistoryViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        event["timeFrameOptions"] = Self.timeFrameOptions
        callJS("window.basilTranscriptionHistory && window.basilTranscriptionHistory.onEvent", args: event)
    }

    func sendSnapshot(viewModel: TranscriptionHistoryViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilTranscriptionHistory && window.basilTranscriptionHistory.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilTranscriptionHistory && window.basilTranscriptionHistory.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilTranscriptionHistory && window.basilTranscriptionHistory.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: TranscriptionHistoryViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "error": viewModel.error as Any? ?? NSNull(),
            "timeFrameId": Self.timeFrameId(for: viewModel.selectedTimeFrame),
            "searchText": viewModel.searchText,
            "currentlyPlayingId": viewModel.currentlyPlayingID as Any? ?? NSNull(),
            "activeRetranscriptionId": viewModel.activeRetranscriptionID as Any? ?? NSNull(),
            "retranscriptionProgressMessage": viewModel.retranscriptionProgressMessage as Any? ?? NSNull(),
            "retranscriptionProgressFraction": viewModel.retranscriptionProgressFraction as Any? ?? NSNull(),
            "currentGlobalTranscriptionModelId": viewModel.currentGlobalTranscriptionModelId,
            "availableRetranscriptionModels": viewModel.availableRetranscriptionModels.map(Self.modelOptionPayload),
            "transcriptions": viewModel.transcriptions.map(Self.recordPayload),
        ]
    }

    private static func recordPayload(_ record: TranscriptionRecord) -> [String: Any] {
        [
            "id": record.id,
            "formattedDate": record.formattedDate,
            "formattedLastTranscribedDate": record.formattedLastTranscribedDate as Any? ?? NSNull(),
            "formattedDuration": record.formattedDuration,
            "displayText": record.displayText,
            "modelName": record.modelName,
            "status": record.statusKind.rawValue,
            "errorMessage": record.errorMessage as Any? ?? NSNull(),
        ]
    }

    private static func modelOptionPayload(_ model: TranscriptionModelOption) -> [String: Any] {
        [
            "id": model.id,
            "displayName": model.displayName,
            "isApiModel": model.isApiModel,
            "provider": model.provider as Any? ?? NSNull(),
        ]
    }

    private static func timeFrameId(for timeFrame: TranscriptionHistoryViewModel.TimeFrame) -> String {
        switch timeFrame {
        case .day: return "day"
        case .week: return "week"
        case .month: return "month"
        case .all: return "all"
        }
    }

    /// Mirrors `TranscriptionHistoryViewModel.TimeFrame.allCases` -- sent
    /// once in `init` since this fixed list never changes at runtime.
    private static let timeFrameOptions: [[String: String]] = [
        ["id": "day", "label": "24 Hours"],
        ["id": "week", "label": "7 Days"],
        ["id": "month", "label": "30 Days"],
        ["id": "all", "label": "All Time"],
    ]
}
