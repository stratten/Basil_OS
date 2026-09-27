import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactTranscriptionHistoryWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestSetTimeFrame: ((String, String) -> Void)?
    var onRequestSetSearchText: ((String, String) -> Void)?
    var onRequestPlayAudio: ((String, String) -> Void)?
    var onRequestStopAudio: ((String) -> Void)?
    var onRequestRetranscribe: ((String, String, String?) -> Void)?
    var onRequestDeleteTranscription: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactTranscriptionHistoryWeakScriptMessageHandler(self),
            name: "basilTranscriptionHistoryBridge"
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
                    "[TRANSCRIPTION_HISTORY_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactTranscriptionHistoryWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilTranscriptionHistoryBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilTranscriptionHistoryBridge",
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
        case "requestSetTimeFrame":
            guard let requestId = body["requestId"] as? String, let timeFrameId = body["timeFrameId"] as? String else {
                onMalformedIntent?("requestSetTimeFrame")
                return
            }
            onRequestSetTimeFrame?(requestId, timeFrameId)
        case "requestSetSearchText":
            guard let requestId = body["requestId"] as? String, let text = body["text"] as? String else {
                onMalformedIntent?("requestSetSearchText")
                return
            }
            onRequestSetSearchText?(requestId, text)
        case "requestPlayAudio":
            guard let requestId = body["requestId"] as? String, let transcriptionId = body["transcriptionId"] as? String else {
                onMalformedIntent?("requestPlayAudio")
                return
            }
            onRequestPlayAudio?(requestId, transcriptionId)
        case "requestStopAudio":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestStopAudio")
                return
            }
            onRequestStopAudio?(requestId)
        case "requestRetranscribe":
            guard let requestId = body["requestId"] as? String, let transcriptionId = body["transcriptionId"] as? String else {
                onMalformedIntent?("requestRetranscribe")
                return
            }
            onRequestRetranscribe?(requestId, transcriptionId, body["modelId"] as? String)
        case "requestDeleteTranscription":
            guard let requestId = body["requestId"] as? String, let transcriptionId = body["transcriptionId"] as? String else {
                onMalformedIntent?("requestDeleteTranscription")
                return
            }
            onRequestDeleteTranscription?(requestId, transcriptionId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactTranscriptionHistoryWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactTranscriptionHistoryWebView?

    init(_ target: ReactTranscriptionHistoryWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
