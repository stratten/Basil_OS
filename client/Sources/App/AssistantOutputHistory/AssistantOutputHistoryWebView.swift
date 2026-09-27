import AppKit
@preconcurrency import WebKit

@MainActor
final class AssistantOutputHistoryWebView: NSObject {
    let webView: WKWebView

    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onToggleChromeCollapse: ((Bool) -> Void)?
    var onRefineFromHistory: ((Int) -> Void)?
    var onReady: (() -> Void)?

    private(set) var hasReceivedReadyAck = false
    private(set) var dragAreaView: WindowDragAreaView?

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        super.init()
        configuration.userContentController.add(AssistantOutputHistoryWeakScriptMessageHandler(self), name: "assistantOutputHistoryBridge")
        webView.navigationDelegate = self
    }

    func installDragArea(headerHeight: CGFloat = 44) {
        let dragView = WindowDragAreaView(leadingInteractiveWidth: 92, trailingInteractiveWidth: 0)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: headerHeight),
        ])
        dragAreaView = dragView
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else { return }
        let webAssetsFolder = resourceURL.appendingPathComponent("AssistantSessionWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/assistant-output-history.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            #if DEBUG
            DevLogger.shared.error("[ASSISTANT_OUTPUT_HISTORY_WEB] Staged HTML not found at \(htmlURL.path)", context: "AssistantOutputHistoryWebView")
            #endif
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
    }

    func sendInit(baseUrl: String, anchoredToWidget: Bool, theme: [String: Any]) {
        let event: [String: Any] = [
            "type": "init",
            "baseUrl": baseUrl,
            "anchoredToWidget": anchoredToWidget,
            "theme": theme,
        ]
        callJS(with: event)
    }

    func sendThemeChanged(theme: [String: Any]) {
        var event = theme
        event["type"] = "themeChanged"
        callJS(with: event)
    }

    func sendHistoryUpdated() {
        callJS(with: ["type": "historyUpdated"])
    }

    func sendHistoryActionError(_ message: String) {
        callJS(with: ["type": "historyActionError", "message": message])
    }

    private func callJS(with dict: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(dict),
              let data = try? JSONSerialization.data(withJSONObject: dict),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.basilAssistantOutputHistory && window.basilAssistantOutputHistory.onEvent(\(json))")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "assistantOutputHistoryBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else { return }
        switch type {
        case "historyWidgetReady":
            hasReceivedReadyAck = true
            onReady?()
        case "closeWindow":
            onClose?()
        case "minimizeWindow":
            onMinimize?()
        case "toggleChromeCollapse":
            onToggleChromeCollapse?(body["collapsed"] as? Bool ?? false)
        case "refineFromHistory":
            let assistantOutputId = (body["assistantOutputId"] as? Int)
                ?? (body["assistantOutputId"] as? NSNumber)?.intValue
            guard let assistantOutputId else { return }
            onRefineFromHistory?(assistantOutputId)
        case "copyHistoryMarkdown":
            guard let content = body["content"] as? String else { return }
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            pasteboard.setString(content, forType: .string)
        case "copyHistoryRichText":
            guard let content = body["content"] as? String else { return }
            let pasteboard = NSPasteboard.general
            pasteboard.clearContents()
            let attributedString = MarkdownUtils.markdownToAttributedString(content)
            pasteboard.setString(attributedString.string, forType: .string)
            if MarkdownUtils.containsMarkdown(content),
               let rtfData = attributedString.rtf(
                from: NSRange(location: 0, length: attributedString.length),
                documentAttributes: [:]
               ) {
                pasteboard.setData(rtfData, forType: .rtf)
            }
        case "openHistoryExternalUrl":
            guard let rawURL = body["url"] as? String,
                  let url = URL(string: rawURL),
                  url.scheme == "https" || url.scheme == "http" else { return }
            NSWorkspace.shared.open(url)
        default:
            break
        }
    }
}

extension AssistantOutputHistoryWebView: WKNavigationDelegate {}

private final class AssistantOutputHistoryWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: AssistantOutputHistoryWebView?
    init(_ target: AssistantOutputHistoryWebView) { self.target = target }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
