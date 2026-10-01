import AppKit
@preconcurrency import WebKit

/// Hosts the React-based main Meeting Assistant UI via WKWebView. Mirrors the
/// structure of `AgentTaskResultWebView`: a thin host class plus
/// `+OutgoingBridge`/`+IncomingBridge` extensions in the same directory.
@MainActor
final class MeetingAssistantWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let instanceId = UUID().uuidString
    let webView: WKWebView
    private let userContentController: WKUserContentController
    var dragAreaView: WindowDragAreaView?
    var dragAreaHeightConstraint: NSLayoutConstraint?
    var hasReceivedReady = false
    var isEmbedded = false
    private var allowedAssetRootURL: URL?

    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onToggleCollapse: ((Bool) -> Void)?
    var onIntent: ((MeetingBridgeIntent, [String: Any]) -> Void)?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        self.userContentController = configuration.userContentController

        super.init()

        configuration.userContentController.add(self, name: "meetingBridge")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    /// Fixed pass-through bands, identical strategy to
    /// `AgentTaskResultWebView.installDragArea()`: the header's button
    /// clusters sit in the same fixed-width bands on every render, so a
    /// dynamic per-element region report is unnecessary and (as observed)
    /// prone to going stale relative to the live layout. `leadingInteractiveWidth`
    /// covers the close/minimize/collapse cluster (`.meeting-window-chrome-actions`,
    /// 3 x 22pt buttons); `trailingInteractiveWidth` covers whichever
    /// trailing content (recording bubble alone, or bubble/Copy All/Export)
    /// the caller's window renders.
    func installDragArea(headerHeight: CGFloat = 44, leadingInteractiveWidth: CGFloat = 90, trailingInteractiveWidth: CGFloat = 76) {
        dragAreaView?.removeFromSuperview()
        let dragView = WindowDragAreaView(leadingInteractiveWidth: leadingInteractiveWidth, trailingInteractiveWidth: trailingInteractiveWidth)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        let heightConstraint = dragView.heightAnchor.constraint(equalToConstant: headerHeight)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            heightConstraint,
        ])
        self.dragAreaView = dragView
        self.dragAreaHeightConstraint = heightConstraint
    }

    func updateDragAreaHeight(_ height: CGFloat) {
        guard height.isFinite, height > 0, dragAreaHeightConstraint?.constant != height else {
            return
        }
        dragAreaHeightConstraint?.constant = height
    }

    func prepareEmbeddedPresentation() {
        isEmbedded = true
        userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.dataset.meetingAssistantEmbedded = 'true';",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
    }

    func loadContent(entryFile: String) {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[MeetingAssistantWebView] Could not get bundle resource URL", context: "LiveTranscription")
            #endif
            return
        }
        let webAssetsFolder = resourceURL.appendingPathComponent("MeetingAssistantWebAssets")
        allowedAssetRootURL = webAssetsFolder.standardizedFileURL
        let htmlURL = webAssetsFolder.appendingPathComponent(entryFile)
        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[MeetingAssistantWebView \(instanceId)] HTML file NOT found at: \(htmlURL.path)", context: "LiveTranscription")
            #endif
        }
    }

    /// WKNavigationDelegate: content-process termination recovery. Swift
    /// never treats this as a session-ending event; it only re-loads the
    /// static asset. React re-sends `reactReady` on the reload and the
    /// coordinator answers with a fresh snapshot -- the underlying recording
    /// session is untouched because it lives on `MeetingSessionCoordinator`,
    /// not in this view.
    nonisolated func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.hasReceivedReady = false
            #if DEBUG
            DevLogger.shared.error("[MeetingAssistantWebView \(self.instanceId)] Content process terminated, reloading", context: "LiveTranscription")
            #endif
            self.webView.reload()
        }
    }

    /// Only local file navigations inside the staged asset bundle are
    /// permitted; anything else (an accidental external link, a malformed
    /// deep link) is canceled rather than navigated.
    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if let url = navigationAction.request.url?.standardizedFileURL,
           url.isFileURL,
           let allowedAssetRootURL,
           url.path.hasPrefix(allowedAssetRootURL.path + "/") {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
        }
    }

    func tearDown() {
        hasReceivedReady = false
        webView.navigationDelegate = nil
        userContentController.removeScriptMessageHandler(forName: "meetingBridge")
    }
}
