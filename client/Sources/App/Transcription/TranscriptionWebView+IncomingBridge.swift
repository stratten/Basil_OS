import WebKit

extension TranscriptionWebView {
    func handleScriptMessage(_ message: WKScriptMessage) {
        if message.name == "jsLog" {
            #if DEBUG
            if let body = message.body as? [String: Any] {
                let kind = (body["kind"] as? String) ?? (body["level"] as? String) ?? "log"
                let text = (body["message"] as? String) ?? ""
                DevLogger.shared.info("[TRANSCRIPTION_WIDGET_WEB:\(kind)] \(text)", context: "TranscriptionWebView")
            }
            #endif
            return
        }

        guard message.name == "transcriptionWidgetBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }

        switch type {
        case "reactReady":
            guard (body["protocolVersion"] as? NSNumber)?.intValue == 1 else {
                #if DEBUG
                DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] React reported an unsupported protocol version", context: "TranscriptionWebView")
                #endif
                return
            }
            markReadyFromReact()
        case "requestResize":
            guard let width = body["width"] as? Double, let height = body["height"] as? Double else { return }
            onResize?(CGFloat(width), CGFloat(height))
        default:
            onIntent?(body)
        }
    }
}
