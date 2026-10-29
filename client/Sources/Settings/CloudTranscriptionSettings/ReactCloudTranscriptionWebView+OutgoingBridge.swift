import Foundation

@MainActor
protocol ReactCloudTranscriptionBridgeOutput: AnyObject {
    func sendState(_ state: [String: Any])
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactCloudTranscriptionWebView: ReactCloudTranscriptionBridgeOutput {
    private static let handler = "window.basilCloudTranscription && window.basilCloudTranscription.onEvent"

    func sendState(_ state: [String: Any]) {
        callJS(Self.handler, args: ["type": "state", "state": state] as [String: Any])
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS(Self.handler, args: event)
    }

    func sendLoadError(message: String) {
        callJS(Self.handler, args: ["type": "loadError", "message": message] as [String: Any])
    }
}
