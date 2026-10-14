import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactDateTimeSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onUpdateDateDisplayStyle: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactDateTimeSettingsWeakScriptMessageHandler(self),
            name: "basilDateTimeSettingsBridge"
        )
    }

    func callJS(_ function: String, args: Any...) {
        guard args.count == 1 else { return }
        webView.callBasilEventHandler(
            function,
            event: args[0],
            logTag: "DATE_TIME_SETTINGS_WEB",
            logContext: "ReactDateTimeSettingsWebView"
        )
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilDateTimeSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilDateTimeSettingsBridge",
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
        case "updateDateDisplayStyle":
            guard
                let requestId = body["requestId"] as? String,
                let style = body["dateDisplayStyle"] as? String,
                DateDisplayStyle(rawValue: style) != nil
            else {
                onMalformedIntent?("updateDateDisplayStyle")
                return
            }
            onUpdateDateDisplayStyle?(requestId, style)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactDateTimeSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactDateTimeSettingsWebView?

    init(_ target: ReactDateTimeSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
