import Foundation
@preconcurrency import WebKit

@MainActor
final class SettingsShellBridge: NSObject {
    private let webView: WKWebView

    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onCollapse: (() -> Void)?
    var onExpand: (() -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            SettingsShellWeakScriptMessageHandler(self),
            name: "basilSettingsShellBridge"
        )
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilSettingsShellBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilSettingsShellBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }

        switch type {
        case "close":
            onClose?()
        case "minimize":
            onMinimize?()
        case "collapse":
            onCollapse?()
        case "expand":
            onExpand?()
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class SettingsShellWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: SettingsShellBridge?

    init(_ target: SettingsShellBridge) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
