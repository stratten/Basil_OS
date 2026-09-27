import Foundation

@MainActor
protocol ReactMacContactsSettingsBridgeOutput: AnyObject {
    func sendInit(status: MacContactsStatusResponse)
    func sendSnapshot(status: MacContactsStatusResponse)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactMacContactsSettingsWebView: ReactMacContactsSettingsBridgeOutput {
    func sendInit(status: MacContactsStatusResponse) {
        var event = stateEvent(type: "init", status: status)
        event["protocolVersion"] = 1
        callJS("window.basilMacContactsSettings && window.basilMacContactsSettings.onEvent", args: event)
    }

    func sendSnapshot(status: MacContactsStatusResponse) {
        callJS("window.basilMacContactsSettings && window.basilMacContactsSettings.onEvent", args: stateEvent(type: "snapshot", status: status))
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilMacContactsSettings && window.basilMacContactsSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        callJS(
            "window.basilMacContactsSettings && window.basilMacContactsSettings.onEvent",
            args: ["type": "loadError", "message": message]
        )
    }

    private func stateEvent(type: String, status: MacContactsStatusResponse) -> [String: Any] {
        [
            "type": type,
            "fields": [
                "available": status.available,
                "preferenceEnabled": status.preferenceEnabled,
                "authorizationStatus": status.authorizationStatus,
                "canLookup": status.canLookup,
                "detail": status.detail as Any? ?? NSNull(),
            ],
        ]
    }
}
