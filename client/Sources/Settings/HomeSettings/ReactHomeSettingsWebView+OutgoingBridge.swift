import Foundation

@MainActor
protocol ReactHomeSettingsBridgeOutput: AnyObject {
    func sendInit(fields: HomeSettingsFields)
    func sendSnapshot(fields: HomeSettingsFields)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactHomeSettingsWebView: ReactHomeSettingsBridgeOutput {
    func sendInit(fields: HomeSettingsFields) {
        var event = stateEvent(type: "init", fields: fields)
        event["protocolVersion"] = 1
        callJS("window.basilHomeSettings && window.basilHomeSettings.onEvent", args: event)
    }

    func sendSnapshot(fields: HomeSettingsFields) {
        let event = stateEvent(type: "snapshot", fields: fields)
        callJS("window.basilHomeSettings && window.basilHomeSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilHomeSettings && window.basilHomeSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilHomeSettings && window.basilHomeSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, fields: HomeSettingsFields) -> [String: Any] {
        ["type": type, "fields": HomeSettingsPayloadBuilder.makeFieldsPayload(fields)]
    }
}
