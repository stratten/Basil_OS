import AppKit
@preconcurrency import WebKit

@MainActor
final class ModelDownloadMiniPanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let protocolVersion = 1
    static let validWidthRange = 240.0...300.0
    static let validHeightRange = 140.0...420.0

    let webView: WKWebView
    var onRendererReady: (() -> Void)?
    var onDismiss: (() -> Void)?
    var onRetryModel: ((String) -> Void)?
    var onCancelModel: ((String) -> Void)?
    var onResizeRequested: ((CGSize) -> Void)?
    var onNavigationFailed: (() -> Void)?
    var isKnownModelId: ((String) -> Bool)?
    var resourcesURLProvider: () -> URL? = { Bundle.main.resourceURL }

    private var initialSnapshot: ModelDownloadPanelSnapshot?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        super.init()

        configuration.userContentController.add(self, name: "modelDownloadPanelBridge")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func loadContent(snapshot: ModelDownloadPanelSnapshot) {
        initialSnapshot = snapshot
        guard let resourceURL = resourcesURLProvider() else {
            notifyNavigationFailure()
            return
        }
        let assetsURL = resourceURL.appendingPathComponent("ModelDownloadMiniPanelAssets")
        let htmlURL = assetsURL.appendingPathComponent("src/entries/model-download-mini-panel.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            notifyNavigationFailure()
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: assetsURL)
    }

    func sendSnapshot(_ snapshot: ModelDownloadPanelSnapshot) {
        callJavaScript("window.basilModelDownloadPanel.onSnapshot", argument: snapshot.jsonObject(includeAppIcon: false))
    }

    func sendThemeChanged() {
        let payload: [String: Any] = [
            "theme": ModelDownloadMiniPanelTheme.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        webView.evaluateJavaScript("window.basilModelDownloadPanel.onThemeChanged(\(json).theme, \(json).fonts)", completionHandler: nil)
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "modelDownloadPanelBridge")
        webView.navigationDelegate = nil
        onRendererReady = nil
        onDismiss = nil
        onRetryModel = nil
        onCancelModel = nil
        onResizeRequested = nil
        onNavigationFailed = nil
        isKnownModelId = nil
        resourcesURLProvider = { nil }
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.name == "modelDownloadPanelBridge" else { return }
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
            onRendererReady?()
        case "dismiss":
            onDismiss?()
        case "retryModel", "cancelModel":
            guard let modelId = message["modelId"] as? String,
                  !modelId.isEmpty,
                  isKnownModelId?(modelId) == true else {
                return
            }
            if type == "retryModel" {
                onRetryModel?(modelId)
            } else {
                onCancelModel?(modelId)
            }
        case "requestResize":
            guard let widthNumber = message["width"] as? NSNumber,
                  let heightNumber = message["height"] as? NSNumber else {
                return
            }
            let width = widthNumber.doubleValue
            let height = heightNumber.doubleValue
            guard width.isFinite, height.isFinite,
                  Self.validWidthRange.contains(width),
                  Self.validHeightRange.contains(height) else {
                return
            }
            onResizeRequested?(CGSize(width: width, height: height))
        default:
            return
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let initialSnapshot else {
            notifyNavigationFailure()
            return
        }
        callJavaScript("window.basilModelDownloadPanel.onInit", argument: [
            "theme": ModelDownloadMiniPanelTheme.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
            "snapshot": initialSnapshot.jsonObject(),
        ])
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
