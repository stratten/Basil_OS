import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactReasoningAPIModelsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestToggleMaster: ((String, Bool) -> Void)?
    var onRequestToggleProvider: ((String, String, Bool) -> Void)?
    var onRequestToggleProviderKeySource: ((String, String, Bool) -> Void)?
    var onRequestToggleModel: ((String, String, String, Bool) -> Void)?
    var onRequestSaveApiKey: ((String, String, String) -> Void)?
    var onRequestRemoveApiKey: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactReasoningAPIModelsWeakScriptMessageHandler(self),
            name: "basilReasoningApiModelsBridge"
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
                    "[REASONING_API_MODELS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactReasoningAPIModelsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilReasoningApiModelsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilReasoningApiModelsBridge",
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
        case "requestToggleMaster":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestToggleMaster")
                return
            }
            onRequestToggleMaster?(requestId, enabled)
        case "requestToggleProvider":
            guard let requestId = body["requestId"] as? String,
                  let providerId = body["providerId"] as? String,
                  let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestToggleProvider")
                return
            }
            onRequestToggleProvider?(requestId, providerId, enabled)
        case "requestToggleProviderKeySource":
            guard let requestId = body["requestId"] as? String,
                  let providerId = body["providerId"] as? String,
                  let useOwnKey = body["useOwnKey"] as? Bool else {
                onMalformedIntent?("requestToggleProviderKeySource")
                return
            }
            onRequestToggleProviderKeySource?(requestId, providerId, useOwnKey)
        case "requestToggleModel":
            guard let requestId = body["requestId"] as? String,
                  let providerId = body["providerId"] as? String,
                  let modelId = body["modelId"] as? String,
                  let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestToggleModel")
                return
            }
            onRequestToggleModel?(requestId, providerId, modelId, enabled)
        case "requestSaveApiKey":
            guard let requestId = body["requestId"] as? String,
                  let providerId = body["providerId"] as? String,
                  let key = body["key"] as? String else {
                onMalformedIntent?("requestSaveApiKey")
                return
            }
            onRequestSaveApiKey?(requestId, providerId, key)
        case "requestRemoveApiKey":
            guard let requestId = body["requestId"] as? String,
                  let providerId = body["providerId"] as? String else {
                onMalformedIntent?("requestRemoveApiKey")
                return
            }
            onRequestRemoveApiKey?(requestId, providerId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactReasoningAPIModelsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactReasoningAPIModelsWebView?

    init(_ target: ReactReasoningAPIModelsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
