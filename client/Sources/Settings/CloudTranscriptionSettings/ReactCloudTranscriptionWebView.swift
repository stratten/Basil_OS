import Foundation
@preconcurrency import WebKit

/// Validates what the Settings page sends for cloud meeting transcription before any of it reaches a URL path or a request body.
enum CloudTranscriptionIntentParser {
    static let providers: Set<String> = ["deepgram", "assemblyai"]
    static let connections: Set<String> = ["own_key", "basil_account"]

    /// The settings patch the backend accepts, or nil when the page sent a key or value it should not.
    static func settingsPatch(from raw: Any?) -> [String: Any]? {
        guard let raw = raw as? [String: Any] else { return nil }
        var patch: [String: Any] = [:]
        for (key, value) in raw {
            switch key {
            case "enabled", "acknowledge_disclosure":
                guard let flag = value as? Bool else { return nil }
                patch[key] = flag
            case "provider":
                guard let provider = value as? String, providers.contains(provider) else { return nil }
                patch[key] = provider
            case "connection":
                guard let connection = value as? String, connections.contains(connection) else { return nil }
                patch[key] = connection
            default:
                return nil
            }
        }
        return patch
    }

    static func provider(from raw: Any?) -> String? {
        guard let provider = raw as? String, providers.contains(provider) else { return nil }
        return provider
    }
}

@MainActor
final class ReactCloudTranscriptionWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSettings: ((String, [String: Any]) -> Void)?
    var onRequestSaveKey: ((String, String, String) -> Void)?
    var onRequestRemoveKey: ((String, String) -> Void)?
    var onRequestCheck: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactCloudTranscriptionWeakScriptMessageHandler(self),
            name: "basilCloudTranscriptionBridge"
        )
    }

    func callJS(_ function: String, args: Any...) {
        guard args.count == 1 else { return }
        webView.callBasilEventHandler(
            function,
            event: args[0],
            logTag: "CLOUD_TRANSCRIPTION_WEB",
            logContext: "ReactCloudTranscriptionWebView"
        )
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilCloudTranscriptionBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilCloudTranscriptionBridge",
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
        case "requestUpdateSettings":
            guard let requestId = body["requestId"] as? String,
                  let patch = CloudTranscriptionIntentParser.settingsPatch(from: body["patch"]) else {
                onMalformedIntent?("requestUpdateSettings")
                return
            }
            onRequestUpdateSettings?(requestId, patch)
        case "requestSaveKey":
            guard let requestId = body["requestId"] as? String,
                  let provider = CloudTranscriptionIntentParser.provider(from: body["provider"]),
                  let key = body["key"] as? String else {
                onMalformedIntent?("requestSaveKey")
                return
            }
            onRequestSaveKey?(requestId, provider, key)
        case "requestRemoveKey":
            guard let requestId = body["requestId"] as? String,
                  let provider = CloudTranscriptionIntentParser.provider(from: body["provider"]) else {
                onMalformedIntent?("requestRemoveKey")
                return
            }
            onRequestRemoveKey?(requestId, provider)
        case "requestCheck":
            guard let requestId = body["requestId"] as? String,
                  let provider = CloudTranscriptionIntentParser.provider(from: body["provider"]) else {
                onMalformedIntent?("requestCheck")
                return
            }
            onRequestCheck?(requestId, provider)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactCloudTranscriptionWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactCloudTranscriptionWebView?

    init(_ target: ReactCloudTranscriptionWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
