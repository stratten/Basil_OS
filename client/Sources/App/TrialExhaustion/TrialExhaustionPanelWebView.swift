import AppKit
@preconcurrency import WebKit

/// WKWebView bridge for the React trial-exhaustion panel. Mirrors
/// `ModelDownloadMiniPanelWebView`'s shape: a dedicated
/// `WKScriptMessageHandler`/`WKNavigationDelegate` on the
/// `trialExhaustionPanelBridge` channel, using a versioned JSON message
/// protocol so old/new bundle-vs-Swift mismatches fail closed rather than
/// silently misbehaving.
@MainActor
final class TrialExhaustionPanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let protocolVersion = 1
    static let validWidthRange = 400.0...560.0
    static let validHeightRange = 300.0...640.0

    let webView: WKWebView
    var onRendererReady: (() -> Void)?
    var onResizeRequested: ((CGSize) -> Void)?
    var onDismiss: (() -> Void)?
    var onSignUp: (() -> Void)?
    var onAddOwnKeys: (() -> Void)?
    var onUseLocalModels: ((String) -> Void)?
    var onNavigationFailed: (() -> Void)?
    var resourcesURLProvider: () -> URL? = { Bundle.main.resourceURL }

    /// Transparent overlay installed by ``installDragArea()``. Held so it
    /// can be removed/reinstalled if the panel is shown more than once.
    private var dragAreaView: WindowDragAreaView?

    private var initialPayload: InitPayload?

    struct InitPayload {
        let remainingBalanceFormatted: String
        let limitFormatted: String
        let isAuthenticated: Bool
        let userEmail: String?
    }

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        super.init()

        configuration.userContentController.add(self, name: "trialExhaustionPanelBridge")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func loadContent(payload: InitPayload) {
        initialPayload = payload
        guard let resourceURL = resourcesURLProvider() else {
            notifyNavigationFailure()
            return
        }
        let assetsURL = resourceURL.appendingPathComponent("TrialExhaustionPanelAssets")
        let htmlURL = assetsURL.appendingPathComponent("src/entries/trial-exhaustion-panel.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            notifyNavigationFailure()
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: assetsURL)
    }

    /// Overlay a transparent ``WindowDragAreaView`` across the panel header so
    /// AppKit can drag the borderless host without consuming the dismiss
    /// button in the top-right corner (mirrors every other WKWebView panel;
    /// `isMovableByWindowBackground` alone does nothing because the WKWebView
    /// swallows mouse events before AppKit sees a "background" click).
    func installDragArea() {
        if let existing = dragAreaView {
            existing.removeFromSuperview()
            dragAreaView = nil
        }
        let topGutter = WebKitWindowChromeAppearance.frameInset
        let headerInnerHeight: CGFloat = 110
        let headerHeight = topGutter + headerInnerHeight
        let dragView = WindowDragAreaView(trailingInteractiveWidth: 40)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: headerHeight),
        ])
        self.dragAreaView = dragView
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
        webView.evaluateJavaScript("window.basilTrialExhaustionPanel.onThemeChanged(\(json).theme, \(json).fonts)", completionHandler: nil)
    }

    func sendUseLocalModelsResult(requestId: String, status: String, message: String? = nil) {
        var result: [String: Any] = ["requestId": requestId, "status": status]
        if let message {
            result["message"] = message
        }
        callJavaScript("window.basilTrialExhaustionPanel.onUseLocalModelsResult", argument: result)
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "trialExhaustionPanelBridge")
        webView.navigationDelegate = nil
        onRendererReady = nil
        onResizeRequested = nil
        onDismiss = nil
        onSignUp = nil
        onAddOwnKeys = nil
        onUseLocalModels = nil
        onNavigationFailed = nil
        resourcesURLProvider = { nil }
        dragAreaView?.removeFromSuperview()
        dragAreaView = nil
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.name == "trialExhaustionPanelBridge" else { return }
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
            // Sent in response to rendererReady rather than unconditionally in
            // didFinish navigation: rendererReady is posted BY the JS bundle
            // itself, from inside the same effect that already called
            // registerInitHandler, so by the time we receive it the page's
            // init handler is guaranteed to exist. Firing onInit from
            // didFinish instead raced the bridge module's own execution for
            // local file:// loads -- if evaluateJavaScript ran before
            // `window.basilTrialExhaustionPanel` existed, the call threw
            // silently (no completion handler) and the init payload was lost
            // forever, leaving the panel stuck on its blank placeholder.
            if let initialPayload {
                callJavaScript("window.basilTrialExhaustionPanel.onInit", argument: [
                    "theme": AestheticWebPayload.themePayload(),
                    "fonts": AestheticWebPayload.fontPayload(),
                    "remainingBalanceFormatted": initialPayload.remainingBalanceFormatted,
                    "limitFormatted": initialPayload.limitFormatted,
                    "isAuthenticated": initialPayload.isAuthenticated,
                    "userEmail": initialPayload.userEmail ?? NSNull(),
                ])
            }
            onRendererReady?()
        case "requestResize":
            guard let widthNumber = message["width"] as? NSNumber,
                  let heightNumber = message["height"] as? NSNumber else { return }
            let width = widthNumber.doubleValue
            let height = heightNumber.doubleValue
            guard width.isFinite, height.isFinite,
                  Self.validWidthRange.contains(width),
                  Self.validHeightRange.contains(height) else { return }
            onResizeRequested?(CGSize(width: width, height: height))
        case "dismiss":
            onDismiss?()
        case "signUp":
            onSignUp?()
        case "addOwnKeys":
            onAddOwnKeys?()
        case "useLocalModels":
            guard let requestId = message["requestId"] as? String, !requestId.isEmpty else { return }
            onUseLocalModels?(requestId)
        default:
            return
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard initialPayload != nil else {
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
