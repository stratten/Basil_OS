import AppKit
@preconcurrency import WebKit

/// WKWebView bridge for the React setup-assistant resume toast: a dedicated
/// `WKScriptMessageHandler`/`WKNavigationDelegate` on the
/// `setupAssistantResumeToastBridge` channel, using a versioned JSON message
/// protocol so old/new bundle-vs-Swift mismatches fail closed rather than
/// silently misbehaving.
@MainActor
final class SetupAssistantResumeToastWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let protocolVersion = 1
    static let validWidthRange = 280.0...400.0
    static let validHeightRange = 80.0...320.0

    let webView: WKWebView
    var onRendererReady: (() -> Void)?
    var onResizeRequested: ((CGSize) -> Void)?
    var onResume: (() -> Void)?
    var onRemindLater: (() -> Void)?
    var onDontRemind: (() -> Void)?
    var onNavigationFailed: (() -> Void)?
    var resourcesURLProvider: () -> URL? = { Bundle.main.resourceURL }

    /// Transparent overlay installed by ``installDragArea()``. Held so it
    /// can be removed/reinstalled if the toast is shown more than once.
    private var dragAreaView: WindowDragAreaView?

    private var didLoadInitialContent = false

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        super.init()

        configuration.userContentController.add(self, name: "setupAssistantResumeToastBridge")
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

    func loadContent() {
        didLoadInitialContent = true
        guard let resourceURL = resourcesURLProvider() else {
            SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] loadContent: resourcesURLProvider returned nil")
            notifyNavigationFailure()
            return
        }
        let assetsURL = resourceURL.appendingPathComponent("SetupAssistantResumeToastAssets")
        let htmlURL = assetsURL.appendingPathComponent("src/entries/setup-assistant-resume-toast.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] loadContent: staged entry HTML not found at \(htmlURL.path)")
            notifyNavigationFailure()
            return
        }
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] loadContent: loading \(htmlURL.path)")
        webView.loadFileURL(htmlURL, allowingReadAccessTo: assetsURL)
    }

    /// Overlay a transparent ``WindowDragAreaView`` across the toast's copy
    /// area so AppKit can drag the borderless host (mirrors every other
    /// WKWebView panel; `isMovableByWindowBackground` alone does nothing
    /// because the WKWebView swallows mouse events before AppKit sees a
    /// "background" click). The toast has no dedicated header chrome, so the
    /// drag region covers the title/subtitle copy above the action buttons.
    func installDragArea() {
        if let existing = dragAreaView {
            existing.removeFromSuperview()
            dragAreaView = nil
        }
        let topGutter = WebKitWindowChromeAppearance.frameInset
        let copyAreaHeight: CGFloat = 76
        let dragHeight = topGutter + copyAreaHeight
        let dragView = WindowDragAreaView(leadingInteractiveWidth: 0, trailingInteractiveWidth: 0)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: dragHeight),
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
        webView.evaluateJavaScript("window.basilSetupAssistantResumeToast.onThemeChanged(\(json).theme, \(json).fonts)", completionHandler: nil)
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "setupAssistantResumeToastBridge")
        webView.navigationDelegate = nil
        onRendererReady = nil
        onResizeRequested = nil
        onResume = nil
        onRemindLater = nil
        onDontRemind = nil
        onNavigationFailed = nil
        resourcesURLProvider = { nil }
        dragAreaView?.removeFromSuperview()
        dragAreaView = nil
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.name == "setupAssistantResumeToastBridge" else { return }
            handleMessage(body: message.body)
        }
    }

    func handleMessage(body: Any) {
        guard let message = body as? [String: Any],
              let type = message["type"] as? String else {
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] handleMessage: malformed payload \(body)")
            return
        }
        guard (message["protocolVersion"] as? NSNumber)?.intValue == Self.protocolVersion else {
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] handleMessage: rejected \"\(type)\" with protocolVersion \(message["protocolVersion"] ?? "nil") (expected \(Self.protocolVersion))")
            return
        }

        switch type {
        case "rendererReady":
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] handleMessage: rendererReady, sending onInit")
            // Sent in response to rendererReady rather than unconditionally in
            // didFinish navigation: rendererReady is a message posted BY the JS
            // bundle itself, from inside the same effect that already called
            // registerInitHandler, so by the time we receive it the page's init
            // handler is guaranteed to exist. Firing onInit from didFinish
            // instead raced the bridge module's own execution for local
            // file:// loads -- if evaluateJavaScript ran before
            // `window.basilSetupAssistantResumeToast` existed, the call threw
            // silently (no completion handler) and the init payload was lost
            // forever, leaving the toast stuck on its placeholder/hidden state.
            callJavaScript("window.basilSetupAssistantResumeToast.onInit", argument: [
                "theme": AestheticWebPayload.themePayload(),
                "fonts": AestheticWebPayload.fontPayload(),
            ])
            onRendererReady?()
        case "resume":
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] handleMessage: resume")
            onResume?()
        case "remindLater":
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] handleMessage: remindLater")
            onRemindLater?()
        case "dontRemind":
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] handleMessage: dontRemind")
            onDontRemind?()
        case "requestResize":
            guard let widthNumber = message["width"] as? NSNumber,
                  let heightNumber = message["height"] as? NSNumber else {
                SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] handleMessage: requestResize missing width/height in \(message)")
                return
            }
            let width = widthNumber.doubleValue
            let height = heightNumber.doubleValue
            guard width.isFinite, height.isFinite,
                  Self.validWidthRange.contains(width),
                  Self.validHeightRange.contains(height) else {
                SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] handleMessage: requestResize out of bounds width=\(width) height=\(height) (allowed width \(Self.validWidthRange), height \(Self.validHeightRange))")
                return
            }
            SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] handleMessage: requestResize width=\(width) height=\(height)")
            onResizeRequested?(CGSize(width: width, height: height))
        default:
            SetupAssistantResumeToastDiagnosticLog.warning("[SetupAssistantResumeToast] handleMessage: unknown message type \"\(type)\"")
            return
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard didLoadInitialContent else {
            SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] didFinish navigation fired without loadContent() having been called")
            notifyNavigationFailure()
            return
        }
        SetupAssistantResumeToastDiagnosticLog.info("[SetupAssistantResumeToast] didFinish navigation: page loaded, awaiting rendererReady")
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] didFail navigation: \(error)")
        notifyNavigationFailure()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        SetupAssistantResumeToastDiagnosticLog.error("[SetupAssistantResumeToast] didFailProvisionalNavigation: \(error)")
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
