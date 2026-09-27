import AppKit
import WebKit

extension AgentTaskCaptureInputWebView {
    /// Sent once, in response to `captureInputReady`.
    func sendInit(port: Int, snapshot: CaptureSnapshot) {
        let payload: [String: Any] = [
            "port": port,
            "agentTaskDisplayName": BasilTeamIdentity.agentTask.displayName,
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
            "snapshot": snapshot.jsonObject,
        ]
        callJS("window.basilAgentTaskCapture.onInit", args: payload)
    }

    func sendSnapshot(_ snapshot: CaptureSnapshot) {
        callJS("window.basilAgentTaskCapture.onSnapshot", args: snapshot.jsonObject)
    }

    /// Dedicated high-frequency channel. Last-value-wins on the JS side.
    func sendAudioLevel(_ level: Float, audioRevision: Int) {
        callJS("window.basilAgentTaskCapture.onAudioLevel", args: Double(level), audioRevision)
    }

    func sendThemeChanged() {
        callJS("window.basilAgentTaskCapture.onThemeChanged", args: AestheticWebPayload.themePayload())
    }

    func sendFontsChanged() {
        callJS("window.basilAgentTaskCapture.onFontsChanged", args: AestheticWebPayload.fontPayload())
    }

    func callJS(_ function: String, args: Any...) {
        guard let argsData = args.map({ value -> String? in
            if let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]),
               let str = String(data: data, encoding: .utf8) {
                return str
            }
            return nil
        }) as [String?]?, argsData.allSatisfy({ $0 != nil }) else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskCaptureInputWebView] Failed to serialize JS call arguments for \(function)", context: "AgentTaskCapture")
            #endif
            return
        }
        let joinedArgs = argsData.compactMap { $0 }.joined(separator: ", ")
        let script = "\(function)(\(joinedArgs));"
        webView.evaluateJavaScript(script) { [weak self] _, error in
            if let error = error {
                #if DEBUG
                DevLogger.shared.error("[AgentTaskCaptureInputWebView \(self?.instanceId ?? "?")] JS eval error: \(error)", context: "AgentTaskCapture")
                #endif
            }
        }
    }
}
