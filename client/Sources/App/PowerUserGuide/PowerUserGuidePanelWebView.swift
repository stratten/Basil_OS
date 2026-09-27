import AppKit
@preconcurrency import WebKit

/// WKWebView bridge for the React Power User Guide panel. Mirrors
/// `AudioFileUploadWebView`'s proven-working ready/init handshake: rather than
/// sending `onInit` from `didFinish` navigation (which can race the React
/// bundle's own module evaluation and silently no-op, leaving the app stuck
/// on its placeholder), Swift waits for the web side's `rendererReady`
/// message before sending `onInit`, and retries with a bounded backoff in
/// case that first send is still somehow missed.
@MainActor
final class PowerUserGuidePanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let protocolVersion = 1

    let webView: WKWebView
    var onRendererReady: (() -> Void)?
    var onDismiss: (() -> Void)?
    var onNavigationFailed: (() -> Void)?
    var resourcesURLProvider: () -> URL? = { Bundle.main.resourceURL }

    private var hasLoadedContent = false
    private var hasReceivedRendererReady = false
    private var initRetryGeneration = UUID()

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        super.init()

        configuration.userContentController.add(self, name: "powerUserGuidePanelBridge")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func loadContent() {
        hasLoadedContent = true
        guard let resourceURL = resourcesURLProvider() else {
            notifyNavigationFailure()
            return
        }
        let assetsURL = resourceURL.appendingPathComponent("PowerUserGuidePanelAssets")
        let htmlURL = assetsURL.appendingPathComponent("src/entries/power-user-guide-panel.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            notifyNavigationFailure()
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: assetsURL)
    }

    func sendThemeChanged() {
        callJavaScript("window.basilPowerUserGuidePanel.onThemeChanged", argument: [
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ])
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "powerUserGuidePanelBridge")
        webView.navigationDelegate = nil
        initRetryGeneration = UUID()
        onRendererReady = nil
        onDismiss = nil
        onNavigationFailed = nil
        resourcesURLProvider = { nil }
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.name == "powerUserGuidePanelBridge" else { return }
            handleMessage(body: message.body)
        }
    }

    func handleMessage(body: Any) {
        guard let message = body as? [String: Any],
              (message["protocolVersion"] as? NSNumber)?.intValue == Self.protocolVersion,
              let type = message["type"] as? String else {
            return
        }

        switch type {
        case "rendererReady":
            guard !hasReceivedRendererReady else { return }
            hasReceivedRendererReady = true
            sendInitWhenReady()
            onRendererReady?()
        case "dismiss":
            onDismiss?()
        default:
            return
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        notifyNavigationFailure()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        notifyNavigationFailure()
    }

    private func sendInitWhenReady(remainingRetries: Int = 5, interval: TimeInterval = 0.35) {
        let generation = UUID()
        initRetryGeneration = generation
        attemptSendInit(generation: generation, remainingRetries: remainingRetries, interval: interval)
    }

    private func attemptSendInit(generation: UUID, remainingRetries: Int, interval: TimeInterval) {
        guard generation == initRetryGeneration else { return }
        callJavaScript("window.basilPowerUserGuidePanel.onInit", argument: [
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ])
        guard remainingRetries > 0 else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + interval) { [weak self] in
            self?.attemptSendInit(generation: generation, remainingRetries: remainingRetries - 1, interval: interval)
        }
    }

    private func callJavaScript(_ function: String, argument: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(argument),
              let data = try? JSONSerialization.data(withJSONObject: argument),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        webView.evaluateJavaScript("\(function)(\(json))", completionHandler: nil)
    }

    private func notifyNavigationFailure() {
        onNavigationFailed?()
    }
}
