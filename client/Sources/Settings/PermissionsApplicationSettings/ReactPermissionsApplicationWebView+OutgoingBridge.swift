import Foundation

@MainActor
protocol ReactPermissionsApplicationBridgeOutput: AnyObject {
    func sendInit(snapshot: SetupPermissionsStatusSnapshot)
    func sendSnapshot(snapshot: SetupPermissionsStatusSnapshot)
    func sendIntentResult(requestId: String, status: String, message: String?)
}

extension ReactPermissionsApplicationWebView: ReactPermissionsApplicationBridgeOutput {
    func sendInit(snapshot: SetupPermissionsStatusSnapshot) {
        var event = stateEvent(type: "init", snapshot: snapshot)
        event["protocolVersion"] = 1
        callJS("window.basilPermissionsApplication && window.basilPermissionsApplication.onEvent", args: event)
    }

    func sendSnapshot(snapshot: SetupPermissionsStatusSnapshot) {
        let event = stateEvent(type: "snapshot", snapshot: snapshot)
        callJS("window.basilPermissionsApplication && window.basilPermissionsApplication.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilPermissionsApplication && window.basilPermissionsApplication.onEvent", args: event)
    }

    private func stateEvent(type: String, snapshot: SetupPermissionsStatusSnapshot) -> [String: Any] {
        [
            "type": type,
            "permissions": [
                "microphone": snapshot.microphone,
                "accessibility": snapshot.accessibility,
                "inputMonitoring": snapshot.inputMonitoring,
                "screenRecording": snapshot.screenRecording,
                "appleEvents": snapshot.appleEvents,
            ],
        ]
    }
}
