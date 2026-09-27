import WebKit

extension AudioFileUploadWebView {
    func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "audioFileUploadBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }

        if type == "reactReady" {
            guard (body["protocolVersion"] as? NSNumber)?.intValue == 1 else {
                #if DEBUG
                DevLogger.shared.error("[AUDIO_UPLOAD_WEB] React reported an unsupported protocol version", context: "AudioFileUploadWebView")
                #endif
                return
            }
            markReadyFromReact()
            return
        }

        onIntent?(body)
    }
}
