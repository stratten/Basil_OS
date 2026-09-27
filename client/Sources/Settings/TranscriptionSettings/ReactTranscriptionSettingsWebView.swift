import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactTranscriptionSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSelectedModel: ((String, String) -> Void)?
    var onRequestUpdateUnloadDelay: ((String, Int) -> Void)?
    var onRequestUpdateAutoPaste: ((String, Bool) -> Void)?
    var onRequestUpdateAutoCloseOnPaste: ((String, Bool) -> Void)?
    var onRequestUpdateMeetingDetectionStartup: ((String, Bool) -> Void)?
    var onRequestUpdatePushToTalk: ((String, Bool) -> Void)?
    var onRequestUpdatePushToTalkThreshold: ((String, Int) -> Void)?
    var onRequestUpdateTextReplacements: ((String, [TranscriptionTextReplacementRule]) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactTranscriptionSettingsWeakScriptMessageHandler(self),
            name: "basilTranscriptionSettingsBridge"
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
                    "[TRANSCRIPTION_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactTranscriptionSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilTranscriptionSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilTranscriptionSettingsBridge",
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
        case "requestUpdateSelectedModel":
            guard let requestId = body["requestId"] as? String, let modelId = body["modelId"] as? String else {
                onMalformedIntent?("requestUpdateSelectedModel")
                return
            }
            onRequestUpdateSelectedModel?(requestId, modelId)
        case "requestUpdateUnloadDelay":
            guard let requestId = body["requestId"] as? String, let seconds = (body["seconds"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateUnloadDelay")
                return
            }
            onRequestUpdateUnloadDelay?(requestId, seconds)
        case "requestUpdateAutoPaste":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoPaste")
                return
            }
            onRequestUpdateAutoPaste?(requestId, enabled)
        case "requestUpdateAutoCloseOnPaste":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoCloseOnPaste")
                return
            }
            onRequestUpdateAutoCloseOnPaste?(requestId, enabled)
        case "requestUpdateMeetingDetectionStartup":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateMeetingDetectionStartup")
                return
            }
            onRequestUpdateMeetingDetectionStartup?(requestId, enabled)
        case "requestUpdatePushToTalk":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdatePushToTalk")
                return
            }
            onRequestUpdatePushToTalk?(requestId, enabled)
        case "requestUpdatePushToTalkThreshold":
            guard let requestId = body["requestId"] as? String, let thresholdMs = (body["thresholdMs"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdatePushToTalkThreshold")
                return
            }
            onRequestUpdatePushToTalkThreshold?(requestId, thresholdMs)
        case "requestUpdateTextReplacements":
            guard let requestId = body["requestId"] as? String,
                  let rawRules = body["rules"] as? [[String: Any]] else {
                onMalformedIntent?("requestUpdateTextReplacements")
                return
            }
            let rules = rawRules.compactMap { rawRule -> TranscriptionTextReplacementRule? in
                guard let source = rawRule["source"] as? String,
                      let replacement = rawRule["replacement"] as? String else {
                    return nil
                }
                return TranscriptionTextReplacementRule(
                    source: source,
                    replacement: replacement
                )
            }
            guard rules.count == rawRules.count else {
                onMalformedIntent?("requestUpdateTextReplacements")
                return
            }
            onRequestUpdateTextReplacements?(requestId, rules)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactTranscriptionSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactTranscriptionSettingsWebView?

    init(_ target: ReactTranscriptionSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
