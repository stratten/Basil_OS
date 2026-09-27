import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactSkillsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSkillAfterTaskEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateSkillDailyEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateSkillDailyTimeLocal: ((String, String) -> Void)?
    var onRequestUpdateSkillProcessingModel: ((String, String?) -> Void)?
    var onRequestUpdateSkillReconciliationMinInstances: ((String, Int) -> Void)?
    var onRequestDeclineCandidate: ((String, String) -> Void)?
    var onRequestDeleteSkill: ((String, String) -> Void)?
    var onRequestRunIntelligenceNow: ((String) -> Void)?
    var onOpenSkillCandidate: ((String) -> Void)?
    var onOpenSkill: ((String) -> Void)?
    var onOpenReconciliationWorkspace: (() -> Void)?
    var onFocusReconciliationWorkspace: (() -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactSkillsSettingsWeakScriptMessageHandler(self),
            name: "basilSkillsSettingsBridge"
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
                    "[SKILLS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactSkillsSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilSkillsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilSkillsSettingsBridge",
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
        case "requestUpdateSkillAfterTaskEnabled":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateSkillAfterTaskEnabled")
                return
            }
            onRequestUpdateSkillAfterTaskEnabled?(requestId, enabled)
        case "requestUpdateSkillDailyEnabled":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateSkillDailyEnabled")
                return
            }
            onRequestUpdateSkillDailyEnabled?(requestId, enabled)
        case "requestUpdateSkillDailyTimeLocal":
            guard let requestId = body["requestId"] as? String, let time = body["time"] as? String else {
                onMalformedIntent?("requestUpdateSkillDailyTimeLocal")
                return
            }
            onRequestUpdateSkillDailyTimeLocal?(requestId, time)
        case "requestUpdateSkillProcessingModel":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestUpdateSkillProcessingModel")
                return
            }
            let modelId = body["modelId"] as? String
            onRequestUpdateSkillProcessingModel?(requestId, modelId)
        case "requestUpdateSkillReconciliationMinInstances":
            guard let requestId = body["requestId"] as? String,
                  let minInstances = (body["minInstances"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateSkillReconciliationMinInstances")
                return
            }
            onRequestUpdateSkillReconciliationMinInstances?(requestId, minInstances)
        case "requestDeclineCandidate":
            guard let requestId = body["requestId"] as? String, let id = body["id"] as? String else {
                onMalformedIntent?("requestDeclineCandidate")
                return
            }
            onRequestDeclineCandidate?(requestId, id)
        case "requestDeleteSkill":
            guard let requestId = body["requestId"] as? String, let slug = body["slug"] as? String else {
                onMalformedIntent?("requestDeleteSkill")
                return
            }
            onRequestDeleteSkill?(requestId, slug)
        case "requestRunIntelligenceNow":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestRunIntelligenceNow")
                return
            }
            onRequestRunIntelligenceNow?(requestId)
        case "openSkillCandidate":
            guard let id = body["id"] as? String else {
                onMalformedIntent?("openSkillCandidate")
                return
            }
            onOpenSkillCandidate?(id)
        case "openSkill":
            guard let slug = body["slug"] as? String else {
                onMalformedIntent?("openSkill")
                return
            }
            onOpenSkill?(slug)
        case "openReconciliationWorkspace":
            onOpenReconciliationWorkspace?()
        case "focusReconciliationWorkspace":
            onFocusReconciliationWorkspace?()
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactSkillsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactSkillsSettingsWebView?

    init(_ target: ReactSkillsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
