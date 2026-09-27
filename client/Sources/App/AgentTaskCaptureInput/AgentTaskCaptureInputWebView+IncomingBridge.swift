import AppKit
@preconcurrency import WebKit

extension AgentTaskCaptureInputWebView {
    // MARK: - WKScriptMessageHandler

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(name: message.name, body: message.body)
        }
    }

    func handleMessage(name: String, body: Any) {
        if name == "jsLog" {
            if let dict = body as? [String: Any] {
                let level = dict["level"] as? String ?? "log"
                let args = (dict["args"] as? [String])?.joined(separator: " ") ?? ""
                #if DEBUG
                DevLogger.shared.info("[AgentTaskCaptureInputWebView JS \(level.uppercased())] \(args)", context: "AgentTaskCapture")
                #endif
            }
            return
        }

        guard name == "agentTaskCaptureBridge" else { return }

        guard let intent = CaptureInputMessage.parse(body: body) else {
            #if DEBUG
            DevLogger.shared.warning("[AgentTaskCaptureInputWebView] Malformed bridge message (no recognizable type field)", context: "AgentTaskCapture")
            #endif
            return
        }

        if case .captureInputReady = intent {
            isReactReady = true
            onReactReady?()
            return
        }

        if case .unknown(let rawType) = intent {
            #if DEBUG
            DevLogger.shared.warning("[AgentTaskCaptureInputWebView] Unrecognized/malformed intent type: \(rawType)", context: "AgentTaskCapture")
            #endif
            return
        }

        onMessage?(intent)
    }
}
