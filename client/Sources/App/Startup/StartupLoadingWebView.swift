import AppKit
@preconcurrency import WebKit

@MainActor
final class StartupLoadingWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let protocolVersion = 1

    let webView: WKWebView
    var onRendererReady: (() -> Void)?
    var onDrawnIn: (() -> Void)?
    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onCollapse: (() -> Void)?
    var onExpand: (() -> Void)?
    var onNavigationFailed: (() -> Void)?
    var resourcesURLProvider: () -> URL? = { Bundle.main.resourceURL }

    private var initialMessage = "Starting Basil..."
    private var didLoadInitialContent = false

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        super.init()

        configuration.userContentController.add(self, name: "startupLoadingWindowBridge")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        #if DEBUG
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }
        #endif
    }

    func loadContent(message: String) {
        initialMessage = message
        didLoadInitialContent = true
        guard let resourceURL = resourcesURLProvider() else {
            notifyNavigationFailure()
            return
        }
        let assetsURL = resourceURL.appendingPathComponent("StartupLoadingWindowAssets")
        let htmlURL = assetsURL.appendingPathComponent("src/entries/startup-loading.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            notifyNavigationFailure()
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: assetsURL)
    }

    func sendThemeChanged() {
        let payload: [String: Any] = [
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        webView.evaluateJavaScript("window.basilStartupLoadingWindow.onThemeChanged(\(json).theme, \(json).fonts)", completionHandler: nil)
    }

    func sendStatus(_ message: String) {
        callJavaScript("window.basilStartupLoadingWindow.onStatus", argument: ["message": message])
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "startupLoadingWindowBridge")
        webView.navigationDelegate = nil
        onRendererReady = nil
        onDrawnIn = nil
        onClose = nil
        onMinimize = nil
        onCollapse = nil
        onExpand = nil
        onNavigationFailed = nil
        resourcesURLProvider = { nil }
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.name == "startupLoadingWindowBridge" else { return }
            handleMessage(body: message.body)
        }
    }

    func handleMessage(body: Any) {
        guard let message = body as? [String: Any],
              let type = message["type"] as? String else {
            return
        }
        guard (message["protocolVersion"] as? NSNumber)?.intValue == Self.protocolVersion else {
            return
        }

        switch type {
        case "rendererReady":
            callJavaScript("window.basilStartupLoadingWindow.onInit", argument: [
                "theme": AestheticWebPayload.themePayload(),
                "fonts": AestheticWebPayload.fontPayload(),
                "message": initialMessage,
            ])
            onRendererReady?()
        case "drawnIn":
            onDrawnIn?()
        case "close":
            onClose?()
        case "minimize":
            onMinimize?()
        case "collapse":
            onCollapse?()
        case "expand":
            onExpand?()
        default:
            return
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard didLoadInitialContent else {
            notifyNavigationFailure()
            return
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        notifyNavigationFailure()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        notifyNavigationFailure()
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
