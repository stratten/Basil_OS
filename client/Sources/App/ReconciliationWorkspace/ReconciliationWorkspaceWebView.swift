import SwiftUI
@preconcurrency import WebKit

private final class ReconciliationDragAreaView: NSView {
    // Leave the top-left control cluster (close/minimize, see Header.tsx's
    // `.header-left`) clickable; mirrors ProfileEditorDragAreaView's
    // left-exclusion idiom instead of the right-exclusion used by headers
    // whose controls sit on the right.
    private let leftControlWidth: CGFloat = 60

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard bounds.contains(point), point.x >= leftControlWidth else { return nil }
        return self
    }

    override func mouseDown(with event: NSEvent) {
        window?.performDrag(with: event)
    }
}

/// Hosts the Skill Reconciliation Workspace web app. Structural plumbing mirrors
/// ProfileEditorWebView (config injected at document start, transparent webview,
/// top drag strip); the shared AestheticWebPayload feeds the same theme/font
/// payload the Agent Task Result widget uses.
struct ReconciliationWorkspaceWebView: NSViewRepresentable {
    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onCollapse: (() -> Void)?
    var onExpand: (() -> Void)?
    var onCoordinatorReady: ((Coordinator) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(onClose: onClose, onMinimize: onMinimize, onCollapse: onCollapse, onExpand: onExpand)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        configuration.userContentController.add(context.coordinator, name: "basilReconciliation")
        configuration.userContentController.addUserScript(context.coordinator.configScript())

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        context.coordinator.webView = webView
        onCoordinatorReady?(context.coordinator)

        let dragView = ReconciliationDragAreaView()
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: WebKitWindowChromeAppearance.frameInset + 36),
        ])

        context.coordinator.loadContent(in: webView)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private var onClose: (() -> Void)?
        private var onMinimize: (() -> Void)?
        private var onCollapse: (() -> Void)?
        private var onExpand: (() -> Void)?
        weak var webView: WKWebView?

        init(onClose: (() -> Void)?, onMinimize: (() -> Void)?, onCollapse: (() -> Void)?, onExpand: (() -> Void)?) {
            self.onClose = onClose
            self.onMinimize = onMinimize
            self.onCollapse = onCollapse
            self.onExpand = onExpand
        }

        func configScript() -> WKUserScript {
            let port = APIClient.shared.currentPort
            let config: [String: Any] = [
                "apiBaseUrl": APIClient.shared.baseURL,
                "wsUrl": "ws://localhost:\(port)/ws",
                "port": port,
                "theme": AestheticWebPayload.themePayload(),
                "fonts": AestheticWebPayload.fontPayload(),
            ]
            let data = try? JSONSerialization.data(withJSONObject: config, options: [])
            let json = data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
            return WKUserScript(
                source: "window.basilReconciliationConfig = \(json);",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        }

        func sendThemeChanged() {
            let payload: [String: Any] = [
                "theme": AestheticWebPayload.themePayload(),
                "fonts": AestheticWebPayload.fontPayload(),
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: payload),
                  let json = String(data: data, encoding: .utf8) else {
                return
            }
            webView?.evaluateJavaScript(
                "window.basilReconciliationConfig = { ...(window.basilReconciliationConfig || {}), theme: \(json).theme, fonts: \(json).fonts }; window.basilReconciliation?.onThemeChanged?.(\(json).theme, \(json).fonts);"
            )
        }

        func loadContent(in webView: WKWebView) {
            guard let resourceURL = Bundle.main.resourceURL else { return }
            let webAssetsFolder = resourceURL.appendingPathComponent("SkillReconciliationWorkspaceWebAssets")
            let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/skill-reconciliation-workspace.html")
            if FileManager.default.fileExists(atPath: htmlURL.path) {
                webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
            } else {
                DevLogger.shared.error(
                    "[ReconciliationWorkspaceWebView] HTML file not found at \(htmlURL.path)",
                    context: "ReconciliationWorkspace"
                )
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "basilReconciliation",
                  let body = message.body as? [String: Any],
                  let action = body["action"] as? String else {
                return
            }
            if action == "minimize" {
                onMinimize?()
                return
            }
            if action == "close" {
                onClose?()
                return
            }
            if action == "collapse" {
                onCollapse?()
                return
            }
            if action == "expand" {
                onExpand?()
            }
        }
    }
}
