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
        guard let json = Self.serialize(event) else { return }
        sendInitWhenReady(jsonPayload: json)
    }

    func sendSnapshot(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "snapshot"
        event["revision"] = revision
        event["protocolVersion"] = 1
        guard let json = Self.serialize(event) else { return }
        callJS("window.basilAudioFileUpload && window.basilAudioFileUpload.onEvent", jsonArgs: [json])
    }

    func sendDelta(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "delta"
        event["revision"] = revision
        event["protocolVersion"] = 1
        guard let json = Self.serialize(event) else { return }
        callJS("window.basilAudioFileUpload && window.basilAudioFileUpload.onEvent", jsonArgs: [json])
    }

    fileprivate static func serialize(_ dict: [String: Any]) -> String? {
        guard JSONSerialization.isValidJSONObject(dict),
              let data = try? JSONSerialization.data(withJSONObject: dict, options: []) else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }
}
