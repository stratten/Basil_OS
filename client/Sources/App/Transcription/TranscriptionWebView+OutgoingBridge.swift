import Foundation

@MainActor
protocol TranscriptionBridgeOutput: AnyObject {
    func sendInit(theme: [String: Any])
    func sendThemeChanged(theme: [String: Any])
    func sendSnapshot(revision: Int, payload: [String: Any])
    func sendDelta(revision: Int, payload: [String: Any])
    func sendMeter(audioLevel: Float)
    func showTranscriptionModelPicker(
        models: [TranscriptionModelOption],
        selectedModelId: String,
        anchorRect: [String: CGFloat],
        onSelection: @escaping (String) -> Void
    )
}

extension TranscriptionWebView: TranscriptionBridgeOutput {
    func sendInit(theme: [String: Any]) {
        let event: [String: Any] = ["type": "init", "protocolVersion": 1, "theme": theme]
        guard let payload = Self.jsonSafePayload(event) else { return }
        sendInitWhenReady(payload: payload)
    }

    func sendThemeChanged(theme: [String: Any]) {
        var event = theme
        event["type"] = "themeChanged"
        guard let payload = Self.jsonSafePayload(event) else { return }
        callJS("window.basilTranscriptionWidget && window.basilTranscriptionWidget.onEvent", event: payload)
    }

    func sendSnapshot(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "snapshot"
        event["revision"] = revision
        event["protocolVersion"] = 1
        guard let jsonPayload = Self.jsonSafePayload(event) else { return }
        callJS("window.basilTranscriptionWidget && window.basilTranscriptionWidget.onEvent", event: jsonPayload)
    }

    func sendDelta(revision: Int, payload: [String: Any]) {
        var event = payload
        event["type"] = "delta"
        event["revision"] = revision
        event["protocolVersion"] = 1
        guard let jsonPayload = Self.jsonSafePayload(event) else { return }
        callJS("window.basilTranscriptionWidget && window.basilTranscriptionWidget.onEvent", event: jsonPayload)
    }

    func sendMeter(audioLevel: Float) {
        let event: [String: Any] = ["type": "meter", "audioLevel": audioLevel]
        guard let payload = Self.jsonSafePayload(event) else { return }
        callJS("window.basilTranscriptionWidget && window.basilTranscriptionWidget.onEvent", event: payload)
    }

    fileprivate static func jsonSafePayload(_ dict: [String: Any]) -> Any? {
        guard JSONSerialization.isValidJSONObject(dict),
              let data = try? JSONSerialization.data(withJSONObject: dict, options: []) else {
            #if DEBUG
            DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] Failed to serialize bridge event: \(dict)", context: "TranscriptionWebView")
            #endif
            return nil
        }
        return try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
    }
}
