import Foundation

@MainActor
protocol AssistantSessionBridgeOutput: AnyObject {
    func sendInit(theme: [String: Any])
    func sendThemeChanged(theme: [String: Any])
    func sendSnapshot(revision: Int, payload: [String: Any])
    func sendDelta(revision: Int, payload: [String: Any])
    func sendMeter(audioLevel: Float)
}

extension AssistantSessionWebView: AssistantSessionBridgeOutput {
    func sendInit(theme: [String: Any]) {
        let event: [String: Any] = ["type": "init", "protocolVersion": 1, "theme": theme]
        sendInitWhenReady(payload: event)
    }

    func sendThemeChanged(theme: [String: Any]) {
        var event = theme
        event["type"] = "themeChanged"
        callJS("window.basilAssistantSession && window.basilAssistantSession.onEvent", args: event)
    }

    func sendSnapshot(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "snapshot"
        event["revision"] = revision
        event["protocolVersion"] = 1
        callJS("window.basilAssistantSession && window.basilAssistantSession.onEvent", args: event)
    }

    func sendDelta(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "delta"
        event["revision"] = revision
        event["protocolVersion"] = 1
        callJS("window.basilAssistantSession && window.basilAssistantSession.onEvent", args: event)
    }

    func sendMeter(audioLevel: Float) {
        let event: [String: Any] = ["type": "meter", "audioLevel": audioLevel]
        callJS("window.basilAssistantSession && window.basilAssistantSession.onEvent", args: event)
    }
}
