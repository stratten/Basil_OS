import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactModelsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestDownloadModel: ((String, String) -> Void)?
    var onRequestCancelDownload: ((String, String) -> Void)?
    var onRequestDeleteModel: ((String, String) -> Void)?
    var onRequestUpdateVisionFallback: ((String, Bool) -> Void)?
    var onRequestUpdateReasoningFallback: ((String, Bool, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactModelsSettingsWeakScriptMessageHandler(self),
            name: "basilModelsSettingsBridge"
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
                DevLogger.shared.error("[MODELS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactModelsSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilModelsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilModelsSettingsBridge",
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
        case "requestDownloadModel":
            guard let requestId = body["requestId"] as? String, let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestDownloadModel")
                return
            }
            onRequestDownloadModel?(requestId, modelId)
        case "requestCancelDownload":
            guard let requestId = body["requestId"] as? String, let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestCancelDownload")
                return
            }
            onRequestCancelDownload?(requestId, modelId)
        case "requestDeleteModel":
            guard let requestId = body["requestId"] as? String, let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestDeleteModel")
                return
            }
            onRequestDeleteModel?(requestId, modelId)
        case "requestUpdateVisionFallback":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateVisionFallback")
                return
            }
            onRequestUpdateVisionFallback?(requestId, enabled)
        case "requestUpdateReasoningFallback":
            guard let requestId = body["requestId"] as? String,
                  let enabled = body["enabled"] as? Bool,
                  let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestUpdateReasoningFallback")
                return
            }
            onRequestUpdateReasoningFallback?(requestId, enabled, modelId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactModelsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactModelsSettingsWebView?

    init(_ target: ReactModelsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
