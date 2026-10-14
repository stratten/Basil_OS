import Foundation

@MainActor
protocol AudioFileUploadBridgeOutput: AnyObject {
    func sendInit(theme: [String: Any])
    func sendSnapshot(revision: Int, payload: [String: Any])
    func sendDelta(revision: Int, payload: [String: Any])
}

extension AudioFileUploadWebView: AudioFileUploadBridgeOutput {
    func sendInit(theme: [String: Any]) {
        let event: [String: Any] = ["type": "init", "protocolVersion": 1, "theme": theme]
        sendInitWhenReady(event: event)
    }

    func sendSnapshot(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "snapshot"
        event["revision"] = revision
        event["protocolVersion"] = 1
        callJS("window.basilAudioFileUpload && window.basilAudioFileUpload.onEvent", args: event)
    }

    func sendDelta(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "delta"
        event["revision"] = revision
        event["protocolVersion"] = 1
        callJS("window.basilAudioFileUpload && window.basilAudioFileUpload.onEvent", args: event)
    }
}
