import Foundation

@MainActor
protocol ReactDateTimeSettingsBridgeOutput: AnyObject {
    func sendInit(dateDisplayStyle: String)
    func sendSnapshot(dateDisplayStyle: String)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactDateTimeSettingsWebView: ReactDateTimeSettingsBridgeOutput {
    func sendInit(dateDisplayStyle: String) {
        var event = stateEvent(type: "init", dateDisplayStyle: dateDisplayStyle)
        event["protocolVersion"] = 1
        callJS("window.basilDateTimeSettings && window.basilDateTimeSettings.onEvent", args: event)
    }

    func sendSnapshot(dateDisplayStyle: String) {
        let event = stateEvent(type: "snapshot", dateDisplayStyle: dateDisplayStyle)
        callJS("window.basilDateTimeSettings && window.basilDateTimeSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilDateTimeSettings && window.basilDateTimeSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilDateTimeSettings && window.basilDateTimeSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, dateDisplayStyle: String) -> [String: Any] {
        ["type": type, "dateDisplayStyle": dateDisplayStyle]
    }
}
