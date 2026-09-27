import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactBrowserAutomationSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSensitiveFillPolicy: ((String, BrowserSensitiveFillPolicy) -> Void)?
    var onRequestUpdateForegroundControlPolicy: ((String, BrowserForegroundControlPolicy) -> Void)?
    var onRequestUpdateDefaultSessionMode: ((String, BrowserAutomationSessionMode) -> Void)?
    var onRequestUpdatePreferredUserBrowser: ((String, BrowserPreferredUserBrowser) -> Void)?
    var onRequestUpdateShowActionHighlights: ((String, Bool) -> Void)?
    var onRequestUpdateRecordBrowserActionTrace: ((String, Bool) -> Void)?
    var onRequestUpdateAllowVisualFallback: ((String, Bool) -> Void)?
    var onRequestRemoveRememberedDomain: ((String, String) -> Void)?
    var onRequestClearAutomationBrowserProfile: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactBrowserAutomationSettingsWeakScriptMessageHandler(self),
            name: "basilBrowserAutomationSettingsBridge"
        )
    }

    func callJS(_ function: String, args: Any...) {
        guard args.count == 1 else { return }
        webView.callAsyncJavaScript(
            "\(function)(event)",
            arguments: ["event": args[0]],
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error(
                    "[BROWSER_AUTOMATION_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactBrowserAutomationSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilBrowserAutomationSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilBrowserAutomationSettingsBridge",
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
        case "requestUpdateSensitiveFillPolicy":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["policy"] as? String,
                  let policy = BrowserSensitiveFillPolicy(rawValue: raw) else {
                onMalformedIntent?("requestUpdateSensitiveFillPolicy")
                return
            }
            onRequestUpdateSensitiveFillPolicy?(requestId, policy)
        case "requestUpdateForegroundControlPolicy":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["policy"] as? String,
                  let policy = BrowserForegroundControlPolicy(rawValue: raw) else {
                onMalformedIntent?("requestUpdateForegroundControlPolicy")
                return
            }
            onRequestUpdateForegroundControlPolicy?(requestId, policy)
        case "requestUpdateDefaultSessionMode":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["sessionMode"] as? String,
                  let sessionMode = BrowserAutomationSessionMode(rawValue: raw) else {
                onMalformedIntent?("requestUpdateDefaultSessionMode")
                return
            }
            onRequestUpdateDefaultSessionMode?(requestId, sessionMode)
        case "requestUpdatePreferredUserBrowser":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["browser"] as? String,
                  let browser = BrowserPreferredUserBrowser(rawValue: raw) else {
                onMalformedIntent?("requestUpdatePreferredUserBrowser")
                return
            }
            onRequestUpdatePreferredUserBrowser?(requestId, browser)
        case "requestUpdateShowActionHighlights":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateShowActionHighlights")
                return
            }
            onRequestUpdateShowActionHighlights?(requestId, enabled)
        case "requestUpdateRecordBrowserActionTrace":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateRecordBrowserActionTrace")
                return
            }
            onRequestUpdateRecordBrowserActionTrace?(requestId, enabled)
        case "requestUpdateAllowVisualFallback":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAllowVisualFallback")
                return
            }
            onRequestUpdateAllowVisualFallback?(requestId, enabled)
        case "requestRemoveRememberedDomain":
            guard let requestId = body["requestId"] as? String, let domain = body["domain"] as? String else {
                onMalformedIntent?("requestRemoveRememberedDomain")
                return
            }
            onRequestRemoveRememberedDomain?(requestId, domain)
        case "requestClearAutomationBrowserProfile":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestClearAutomationBrowserProfile")
                return
            }
            onRequestClearAutomationBrowserProfile?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactBrowserAutomationSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactBrowserAutomationSettingsWebView?

    init(_ target: ReactBrowserAutomationSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
