import Foundation
@preconcurrency import WebKit

/// Hosts the React token-connect form. The form is React; this type only loads it and carries name, description, and token to the Keychain path.
@MainActor
final class TokenConnectWebView: NSObject {
    let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestConnect: ((String, String, String?, String) -> Void)?
    var onRequestCancel: (() -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        super.init()
        configuration.userContentController.add(
            TokenConnectWeakScriptMessageHandler(self),
            name: "basilTokenConnectBridge"
        )
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else { return }
        let webAssetsFolder = resourceURL.appendingPathComponent("SettingsWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/token-connect.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            DevLogger.shared.error("🔐 Staged token-connect HTML was not found", context: "websocket")
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
    }

    func sendEvent(_ event: [String: Any]) {
        webView.callBasilEventHandler(
            "window.basilTokenConnect && window.basilTokenConnect.onEvent",
            event: event,
            logTag: "TOKEN_CONNECT_WEB",
            logContext: "TokenConnectWebView"
        )
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilTokenConnectBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilTokenConnectBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }
        switch type {
        case "reactReady":
            guard (body["protocolVersion"] as? NSNumber)?.intValue == 1 else {
                onMalformedIntent?("reactReady")
                return
            }
            onReady?()
        case "requestConnect":
            guard let requestId = body["requestId"] as? String,
                  let friendlyName = body["friendlyName"] as? String,
                  let bearerToken = body["bearerToken"] as? String else {
                onMalformedIntent?("requestConnect")
                return
            }
            onRequestConnect?(requestId, friendlyName, body["description"] as? String, bearerToken)
        case "requestCancel":
            onRequestCancel?()
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class TokenConnectWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: TokenConnectWebView?

    init(_ target: TokenConnectWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
