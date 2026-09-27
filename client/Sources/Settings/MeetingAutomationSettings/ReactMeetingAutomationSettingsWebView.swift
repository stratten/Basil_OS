import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactMeetingAutomationSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateAutoRetranscribeOnStop: ((String, Bool) -> Void)?
    var onRequestUpdateAutoRetranscribeDuringRecording: ((String, Bool) -> Void)?
    var onRequestUpdateRetranscribeWindowMinutes: ((String, Double) -> Void)?
    var onRequestUpdateAutoAnalyzeOnComplete: ((String, Bool) -> Void)?
    var onRequestUpdateAutoAnalyzeMode: ((String, String, Bool) -> Void)?
    var onRequestUpdateAutoAnalyzeCustomInstructions: ((String, String) -> Void)?
    var onRequestUpdateAutoAnalyzeTiming: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    private static let allowedTimings: Set<String> = ["after", "before"]

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactMeetingAutomationSettingsWeakScriptMessageHandler(self),
            name: "basilMeetingAutomationSettingsBridge"
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
                    "[MEETING_AUTOMATION_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactMeetingAutomationSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilMeetingAutomationSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilMeetingAutomationSettingsBridge",
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
        case "requestUpdateAutoRetranscribeOnStop":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoRetranscribeOnStop")
                return
            }
            onRequestUpdateAutoRetranscribeOnStop?(requestId, enabled)
        case "requestUpdateAutoRetranscribeDuringRecording":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoRetranscribeDuringRecording")
                return
            }
            onRequestUpdateAutoRetranscribeDuringRecording?(requestId, enabled)
        case "requestUpdateRetranscribeWindowMinutes":
            guard let requestId = body["requestId"] as? String, let minutes = (body["minutes"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateRetranscribeWindowMinutes")
                return
            }
            onRequestUpdateRetranscribeWindowMinutes?(requestId, minutes)
        case "requestUpdateAutoAnalyzeOnComplete":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoAnalyzeOnComplete")
                return
            }
            onRequestUpdateAutoAnalyzeOnComplete?(requestId, enabled)
        case "requestUpdateAutoAnalyzeMode":
            guard let requestId = body["requestId"] as? String,
                  let mode = body["mode"] as? String,
                  let isOn = body["isOn"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoAnalyzeMode")
                return
            }
            onRequestUpdateAutoAnalyzeMode?(requestId, mode, isOn)
        case "requestUpdateAutoAnalyzeCustomInstructions":
            guard let requestId = body["requestId"] as? String, let text = body["text"] as? String else {
                onMalformedIntent?("requestUpdateAutoAnalyzeCustomInstructions")
                return
            }
            onRequestUpdateAutoAnalyzeCustomInstructions?(requestId, text)
        case "requestUpdateAutoAnalyzeTiming":
            guard let requestId = body["requestId"] as? String,
                  let timing = body["timing"] as? String,
                  Self.allowedTimings.contains(timing) else {
                onMalformedIntent?("requestUpdateAutoAnalyzeTiming")
                return
            }
            onRequestUpdateAutoAnalyzeTiming?(requestId, timing)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactMeetingAutomationSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactMeetingAutomationSettingsWebView?

    init(_ target: ReactMeetingAutomationSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
