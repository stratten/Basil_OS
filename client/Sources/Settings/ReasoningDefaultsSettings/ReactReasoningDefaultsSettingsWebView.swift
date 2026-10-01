import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactReasoningDefaultsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSelectedModel: ((String, String) -> Void)?
    var onRequestUpdateCloseAssistantSessionOnInsert: ((String, Bool) -> Void)?
    var onRequestUpdateAutoPasteAssistantOutput: ((String, Bool) -> Void)?
    var onRequestUpdateUseRegionSelection: ((String, Bool) -> Void)?
    var onRequestUpdateAgentTaskDefaultModality: ((String, AgentTaskInputModality) -> Void)?
    var onRequestUpdateAgentTaskAutoReopenOnCompletion: ((String, Bool) -> Void)?
    var onRequestUpdateAgentTaskPushToTalk: ((String, Bool) -> Void)?
    var onRequestUpdateAgentTaskPushToTalkThreshold: ((String, Int) -> Void)?
    var onRequestUpdateAssistantSessionDefaultModality: ((String, AssistantSessionInputMode) -> Void)?
    var onRequestUpdateAssistantSessionPushToTalk: ((String, Bool) -> Void)?
    var onRequestUpdateAssistantSessionPushToTalkThreshold: ((String, Int) -> Void)?
    var onRequestUpdateConversationDefaultConversationOnly: ((String, Bool) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactReasoningDefaultsSettingsWeakScriptMessageHandler(self),
            name: "basilReasoningDefaultsSettingsBridge"
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
                    "[REASONING_DEFAULTS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactReasoningDefaultsSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilReasoningDefaultsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilReasoningDefaultsSettingsBridge",
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
        case "requestUpdateCloseAssistantSessionOnInsert":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateCloseAssistantSessionOnInsert")
                return
            }
            onRequestUpdateCloseAssistantSessionOnInsert?(requestId, enabled)
        case "requestUpdateAutoPasteAssistantOutput":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoPasteAssistantOutput")
                return
            }
            onRequestUpdateAutoPasteAssistantOutput?(requestId, enabled)
        case "requestUpdateUseRegionSelection":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateUseRegionSelection")
                return
            }
            onRequestUpdateUseRegionSelection?(requestId, enabled)
        case "requestUpdateAgentTaskDefaultModality":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["modality"] as? String,
                  let modality = AgentTaskInputModality(rawValue: raw) else {
                onMalformedIntent?("requestUpdateAgentTaskDefaultModality")
                return
            }
            onRequestUpdateAgentTaskDefaultModality?(requestId, modality)
        case "requestUpdateAgentTaskAutoReopenOnCompletion":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAgentTaskAutoReopenOnCompletion")
                return
            }
            onRequestUpdateAgentTaskAutoReopenOnCompletion?(requestId, enabled)
        case "requestUpdateAgentTaskPushToTalk":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAgentTaskPushToTalk")
                return
            }
            onRequestUpdateAgentTaskPushToTalk?(requestId, enabled)
        case "requestUpdateAgentTaskPushToTalkThreshold":
            guard let requestId = body["requestId"] as? String, let thresholdMs = (body["thresholdMs"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateAgentTaskPushToTalkThreshold")
                return
            }
            onRequestUpdateAgentTaskPushToTalkThreshold?(requestId, thresholdMs)
        case "requestUpdateAssistantSessionDefaultModality":
            guard let requestId = body["requestId"] as? String,
                  let raw = body["modality"] as? String,
                  let modality = AssistantSessionInputMode(rawValue: raw) else {
                onMalformedIntent?("requestUpdateAssistantSessionDefaultModality")
                return
            }
            onRequestUpdateAssistantSessionDefaultModality?(requestId, modality)
        case "requestUpdateAssistantSessionPushToTalk":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAssistantSessionPushToTalk")
                return
            }
            onRequestUpdateAssistantSessionPushToTalk?(requestId, enabled)
        case "requestUpdateAssistantSessionPushToTalkThreshold":
            guard let requestId = body["requestId"] as? String, let thresholdMs = (body["thresholdMs"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateAssistantSessionPushToTalkThreshold")
                return
            }
            onRequestUpdateAssistantSessionPushToTalkThreshold?(requestId, thresholdMs)
        case "requestUpdateConversationDefaultConversationOnly":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateConversationDefaultConversationOnly")
                return
            }
            onRequestUpdateConversationDefaultConversationOnly?(requestId, enabled)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactReasoningDefaultsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactReasoningDefaultsSettingsWebView?

    init(_ target: ReactReasoningDefaultsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
