import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactCustomModelsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestCreateModel: ((String, [String: Any]) -> Void)?
    var onRequestUpdateModel: ((String, String, [String: Any]) -> Void)?
    var onRequestDeleteModel: ((String, String, Bool, Bool) -> Void)?
    var onRequestDownloadModel: ((String, String, String) -> Void)?
    var onRequestTestConnection: ((String, [String: Any]) -> Void)?
    var onRequestProbeHFRepo: ((String, String) -> Void)?
    var onRequestFetchGGUFMetadata: ((String, String, String) -> Void)?
    var onRequestFetchLocalGGUFMetadata: ((String, String) -> Void)?
    var onRequestPickLocalFile: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactCustomModelsWeakScriptMessageHandler(self),
            name: "basilCustomModelsBridge"
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
                    "[CUSTOM_MODELS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactCustomModelsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilCustomModelsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilCustomModelsBridge",
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
        case "requestCreateModel":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestCreateModel")
                return
            }
            onRequestCreateModel?(requestId, body)
        case "requestUpdateModel":
            guard let requestId = body["requestId"] as? String,
                  let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestUpdateModel")
                return
            }
            onRequestUpdateModel?(requestId, modelId, body)
        case "requestDeleteModel":
            guard let requestId = body["requestId"] as? String,
                  let modelId = body["modelId"] as? String,
                  let deleteFiles = body["deleteFiles"] as? Bool,
                  let clearHFCache = body["clearHFCache"] as? Bool else {
                onMalformedIntent?("requestDeleteModel")
                return
            }
            onRequestDeleteModel?(requestId, modelId, deleteFiles, clearHFCache)
        case "requestDownloadModel":
            guard let requestId = body["requestId"] as? String,
                  let modelId = body["modelId"] as? String,
                  let filename = body["filename"] as? String else {
                onMalformedIntent?("requestDownloadModel")
                return
            }
            onRequestDownloadModel?(requestId, modelId, filename)
        case "requestTestConnection":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestTestConnection")
                return
            }
            onRequestTestConnection?(requestId, body)
        case "requestProbeHFRepo":
            guard let requestId = body["requestId"] as? String,
                  let url = body["url"] as? String else {
                onMalformedIntent?("requestProbeHFRepo")
                return
            }
            onRequestProbeHFRepo?(requestId, url)
        case "requestFetchGGUFMetadata":
            guard let requestId = body["requestId"] as? String,
                  let repoId = body["repoId"] as? String,
                  let filename = body["filename"] as? String else {
                onMalformedIntent?("requestFetchGGUFMetadata")
                return
            }
            onRequestFetchGGUFMetadata?(requestId, repoId, filename)
        case "requestFetchLocalGGUFMetadata":
            guard let requestId = body["requestId"] as? String,
                  let filePath = body["filePath"] as? String else {
                onMalformedIntent?("requestFetchLocalGGUFMetadata")
                return
            }
            onRequestFetchLocalGGUFMetadata?(requestId, filePath)
        case "requestPickLocalFile":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestPickLocalFile")
                return
            }
            onRequestPickLocalFile?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactCustomModelsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactCustomModelsWebView?

    init(_ target: ReactCustomModelsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
