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
        webView.callBasilFunction(
            function,
            args: args,
            logTag: "AgentTaskCaptureInputWebView \(instanceId)",
            logContext: "AgentTaskCapture"
        )
    }
}
