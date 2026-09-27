import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactTranscriptionAPIModelsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestToggleMaster: ((String, Bool) -> Void)?
    var onRequestToggleProvider: ((String, Bool) -> Void)?
    var onRequestToggleModel: ((String, String, Bool) -> Void)?
    var onRequestSaveApiKey: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactTranscriptionAPIModelsWeakScriptMessageHandler(self),
            name: "basilTranscriptionApiModelsBridge"
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
                    "[TRANSCRIPTION_API_MODELS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactTranscriptionAPIModelsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilTranscriptionApiModelsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilTranscriptionApiModelsBridge",
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
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestToggleProvider")
                return
            }
            onRequestToggleProvider?(requestId, enabled)
        case "requestToggleModel":
            guard let requestId = body["requestId"] as? String,
                  let modelId = body["modelId"] as? String,
                  let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestToggleModel")
                return
            }
            onRequestToggleModel?(requestId, modelId, enabled)
        case "requestSaveApiKey":
            guard let requestId = body["requestId"] as? String, let key = body["key"] as? String else {
                onMalformedIntent?("requestSaveApiKey")
                return
            }
            onRequestSaveApiKey?(requestId, key)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactTranscriptionAPIModelsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactTranscriptionAPIModelsWebView?

    init(_ target: ReactTranscriptionAPIModelsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
