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
    var onRequestSeekAudio: ((String, Double) -> Void)?
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
        webView.callBasilEventHandler(
            function,
            event: args[0],
            logTag: "TRANSCRIPTION_HISTORY_WEB",
            logContext: "ReactTranscriptionHistoryWebView"
        )
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilTranscriptionHistoryBridge")
    }

    /// A seek request needs a transcription id and a finite, non-negative number of seconds; anything else is malformed.
    nonisolated static func parseSeekRequest(_ body: [String: Any]) -> (transcriptionId: String, seconds: Double)? {
        guard let transcriptionId = body["transcriptionId"] as? String, !transcriptionId.isEmpty,
              let seconds = (body["seconds"] as? NSNumber)?.doubleValue,
              seconds.isFinite, seconds >= 0 else {
            return nil
        }
        return (transcriptionId, seconds)
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
        case "requestSeekAudio":
            guard let request = Self.parseSeekRequest(body) else {
                onMalformedIntent?("requestSeekAudio")
                return
            }
            onRequestSeekAudio?(request.transcriptionId, request.seconds)
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
