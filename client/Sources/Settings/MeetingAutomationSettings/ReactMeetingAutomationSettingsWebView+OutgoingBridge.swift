import Foundation

@MainActor
protocol ReactMeetingAutomationSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: TranscriptionSettingsViewModel)
    func sendSnapshot(viewModel: TranscriptionSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactMeetingAutomationSettingsWebView: ReactMeetingAutomationSettingsBridgeOutput {
    func sendInit(viewModel: TranscriptionSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        event["analysisModes"] = Self.analysisModeOptions
        callJS("window.basilMeetingAutomationSettings && window.basilMeetingAutomationSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: TranscriptionSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilMeetingAutomationSettings && window.basilMeetingAutomationSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilMeetingAutomationSettings && window.basilMeetingAutomationSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilMeetingAutomationSettings && window.basilMeetingAutomationSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: TranscriptionSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "settings": [
                "autoRetranscribeOnStop": viewModel.autoRetranscribeOnStop,
                "autoRetranscribeDuringRecording": viewModel.autoRetranscribeDuringRecording,
                "retranscribeWindowMinutes": viewModel.retranscribeWindowMinutes,
                "autoAnalyzeOnComplete": viewModel.autoAnalyzeOnComplete,
                "autoAnalyzeModes": viewModel.autoAnalyzeModes,
                "autoAnalyzeCustomInstructions": viewModel.autoAnalyzeCustomInstructions,
                "autoAnalyzeTiming": viewModel.autoAnalyzeTiming,
            ],
        ]
    }

    /// The six checkbox options for `autoAnalyzeModes`, excluding the free-form `.custom` mode configured by custom instructions. Sent once in `init`; this list never changes at runtime.
    private static let analysisModeOptions: [[String: String]] = [
        ["id": "action_items", "label": "Action Items"],
        ["id": "suggested_actions", "label": "To-Do Candidates"],
        ["id": "summary", "label": "Summary"],
        ["id": "decisions", "label": "Key Decisions"],
        ["id": "questions", "label": "Questions & Answers"],
        ["id": "sentiment", "label": "Sentiment Analysis"],
    ]
}
