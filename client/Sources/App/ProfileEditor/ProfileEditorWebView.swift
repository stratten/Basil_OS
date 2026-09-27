import SwiftUI
@preconcurrency import WebKit

private final class ProfileEditorDragAreaView: NSView {
    private let leftControlWidth: CGFloat = 70

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard bounds.contains(point), point.x >= leftControlWidth else { return nil }
        return self
    }

    override func mouseDown(with event: NSEvent) {
        window?.performDrag(with: event)
    }
}

struct ProfileEditorWebView: NSViewRepresentable {
    let request: ProfileEditorRequest
    var onClosed: ((Bool) -> Void)?
    var onMinimize: (() -> Void)?
    var onOpenSourceTask: ((String) -> Void)?
    var onCoordinatorReady: ((Coordinator) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(request: request, onClosed: onClosed, onMinimize: onMinimize, onOpenSourceTask: onOpenSourceTask)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        configuration.userContentController.add(context.coordinator, name: "basilProfileEditor")
        configuration.userContentController.addUserScript(context.coordinator.configScript())

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        context.coordinator.webView = webView
        onCoordinatorReady?(context.coordinator)

        let dragView = ProfileEditorDragAreaView()
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: 54),
        ])

        context.coordinator.loadContent(in: webView)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private let request: ProfileEditorRequest
        private var onClosed: ((Bool) -> Void)?
        private var onMinimize: (() -> Void)?
        private var onOpenSourceTask: ((String) -> Void)?
        weak var webView: WKWebView?

        init(request: ProfileEditorRequest, onClosed: ((Bool) -> Void)?, onMinimize: (() -> Void)?, onOpenSourceTask: ((String) -> Void)?) {
            self.request = request
            self.onClosed = onClosed
            self.onMinimize = onMinimize
            self.onOpenSourceTask = onOpenSourceTask
        }

        func configScript() -> WKUserScript {
            let config: [String: Any] = [
                "mode": request.mode.rawValue,
                "identifier": request.identifier,
                "apiBaseUrl": APIClient.shared.baseURL,
                "theme": Self.profileEditorThemePayload(),
                "fonts": Self.profileEditorFontPayload(),
            ]
            let data = try? JSONSerialization.data(withJSONObject: config, options: [])
            let json = data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
            return WKUserScript(
                source: "window.basilProfileEditorConfig = \(json);",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        }

        func sendThemeChanged() {
            let payload: [String: Any] = [
                "theme": Self.profileEditorThemePayload(),
                "fonts": Self.profileEditorFontPayload(),
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: payload),
                  let json = String(data: data, encoding: .utf8) else {
                return
            }
            webView?.evaluateJavaScript(
                "window.basilProfileEditorConfig = { ...(window.basilProfileEditorConfig || {}), theme: \(json).theme, fonts: \(json).fonts }; window.basilProfileEditor?.onThemeChanged?.(\(json).theme, \(json).fonts);"
            )
        }

        private static func profileEditorFontPayload() -> [String: Any] {
            AestheticWebPayload.fontPayload()
        }

        private static func profileEditorThemePayload() -> [String: Any] {
            AestheticWebPayload.themePayload()
        }

        func loadContent(in webView: WKWebView) {
            guard let resourceURL = Bundle.main.resourceURL else { return }
            let webAssetsFolder = resourceURL.appendingPathComponent("ProfileMemorySkillsEditorWebAssets")
            let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/profile-editor.html")
            if FileManager.default.fileExists(atPath: htmlURL.path) {
                webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
            } else {
                DevLogger.shared.error("[ProfileEditorWebView] HTML file not found at \(htmlURL.path)", context: "ProfileEditor")
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "basilProfileEditor",
                  let body = message.body as? [String: Any],
                  let action = body["action"] as? String else {
                return
            }
            let didChange = body["didChange"] as? Bool ?? false
            if action == "minimize" {
                onMinimize?()
                return
            }
            if action == "openSourceTask" {
                if let taskId = body["taskId"] as? String, !taskId.isEmpty {
                    onOpenSourceTask?(taskId)
                }
                return
            }
            if action == "saved" || action == "declined" || action == "close" {
                onClosed?(didChange)
            }
        }
    }
}
