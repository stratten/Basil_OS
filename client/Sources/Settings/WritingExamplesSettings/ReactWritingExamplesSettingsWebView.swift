import Foundation
@preconcurrency import WebKit

enum ReactWritingExamplesFilter: String {
    case all
    case emailReply = "email_reply"
    case emailCompose = "email_compose"
    case socialMedia = "social_media"
    case document

    /// `nil` for `.all`, matching the backend's "missing context_type = no filter"
    /// contract exactly (there is no wire value that means "all").
    var apiValue: String? {
        self == .all ? nil : rawValue
    }
}

@MainActor
final class ReactWritingExamplesSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onSetContextFilter: ((ReactWritingExamplesFilter) -> Void)?
    var onRequestDeleteSample: ((String, String) -> Void)?
    var onRequestDeleteAllSamples: ((String, ReactWritingExamplesFilter) -> Void)?
    var onAnalyzeStyle: ((String, ReactWritingExamplesFilter) -> Void)?
    var onCopySampleToClipboard: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactWritingExamplesSettingsWeakScriptMessageHandler(self),
            name: "basilWritingExamplesSettingsBridge"
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
                DevLogger.shared.error("[WRITING_EXAMPLES_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactWritingExamplesSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilWritingExamplesSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilWritingExamplesSettingsBridge",
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
        case "setContextFilter":
            guard
                let rawFilter = body["filter"] as? String,
                let filter = ReactWritingExamplesFilter(rawValue: rawFilter)
            else {
                onMalformedIntent?("setContextFilter")
                return
            }
            onSetContextFilter?(filter)
        case "requestDeleteSample":
            guard
                let requestId = body["requestId"] as? String,
                let id = body["id"] as? String
            else {
                onMalformedIntent?("requestDeleteSample")
                return
            }
            onRequestDeleteSample?(requestId, id)
        case "requestDeleteAllSamples":
            guard
                let requestId = body["requestId"] as? String,
                let rawFilter = body["filter"] as? String,
                let filter = ReactWritingExamplesFilter(rawValue: rawFilter)
            else {
                onMalformedIntent?("requestDeleteAllSamples")
                return
            }
            onRequestDeleteAllSamples?(requestId, filter)
        case "analyzeStyle":
            guard
                let requestId = body["requestId"] as? String,
                let rawFilter = body["filter"] as? String,
                let filter = ReactWritingExamplesFilter(rawValue: rawFilter)
            else {
                onMalformedIntent?("analyzeStyle")
                return
            }
            onAnalyzeStyle?(requestId, filter)
        case "copySampleToClipboard":
            guard let content = body["content"] as? String else {
                onMalformedIntent?("copySampleToClipboard")
                return
            }
            onCopySampleToClipboard?(content)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactWritingExamplesSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactWritingExamplesSettingsWebView?

    init(_ target: ReactWritingExamplesSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
