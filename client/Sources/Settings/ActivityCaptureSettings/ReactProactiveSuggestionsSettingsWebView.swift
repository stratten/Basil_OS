import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactProactiveSuggestionsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateMode: ((String, String) -> Void)?
    var onRequestUpdateFrequencySeconds: ((String, Double) -> Void)?
    var onRequestUpdateEvaluationModel: ((String, String) -> Void)?
    var onRequestUpdateMinimumConfidence: ((String, Double) -> Void)?
    var onRequestUpdateCooldownMinutes: ((String, Double) -> Void)?
    var onRequestUpdateEnabledCapability: ((String, String, Bool) -> Void)?
    var onRequestUpdateAutoExecuteCapability: ((String, String, Bool) -> Void)?
    var onRequestUpdateExcludedAppNames: ((String, [String]) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactProactiveSuggestionsSettingsWeakScriptMessageHandler(self),
            name: "basilProactiveSuggestionsSettingsBridge"
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
                    "[PROACTIVE_SUGGESTIONS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactProactiveSuggestionsSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilProactiveSuggestionsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilProactiveSuggestionsSettingsBridge",
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
        case "requestUpdateEnabled":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateEnabled")
                return
            }
            onRequestUpdateEnabled?(requestId, enabled)
        case "requestUpdateMode":
            guard let requestId = body["requestId"] as? String, let mode = body["mode"] as? String else {
                onMalformedIntent?("requestUpdateMode")
                return
            }
            onRequestUpdateMode?(requestId, mode)
        case "requestUpdateFrequencySeconds":
            guard let requestId = body["requestId"] as? String, let seconds = (body["frequencySeconds"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateFrequencySeconds")
                return
            }
            onRequestUpdateFrequencySeconds?(requestId, seconds)
        case "requestUpdateEvaluationModel":
            guard let requestId = body["requestId"] as? String, let modelId = body["evaluationModel"] as? String else {
                onMalformedIntent?("requestUpdateEvaluationModel")
                return
            }
            onRequestUpdateEvaluationModel?(requestId, modelId)
        case "requestUpdateMinimumConfidence":
            guard let requestId = body["requestId"] as? String, let confidence = (body["minimumConfidence"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateMinimumConfidence")
                return
            }
            onRequestUpdateMinimumConfidence?(requestId, confidence)
        case "requestUpdateCooldownMinutes":
            guard let requestId = body["requestId"] as? String, let minutes = (body["cooldownMinutes"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateCooldownMinutes")
                return
            }
            onRequestUpdateCooldownMinutes?(requestId, minutes)
        case "requestUpdateEnabledCapability":
            guard let requestId = body["requestId"] as? String,
                  let capability = body["capability"] as? String,
                  let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateEnabledCapability")
                return
            }
            onRequestUpdateEnabledCapability?(requestId, capability, enabled)
        case "requestUpdateAutoExecuteCapability":
            guard let requestId = body["requestId"] as? String,
                  let capability = body["capability"] as? String,
                  let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoExecuteCapability")
                return
            }
            onRequestUpdateAutoExecuteCapability?(requestId, capability, enabled)
        case "requestUpdateExcludedAppNames":
            guard let requestId = body["requestId"] as? String, let names = body["excludedAppNames"] as? [String] else {
                onMalformedIntent?("requestUpdateExcludedAppNames")
                return
            }
            onRequestUpdateExcludedAppNames?(requestId, names)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactProactiveSuggestionsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactProactiveSuggestionsSettingsWebView?

    init(_ target: ReactProactiveSuggestionsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
