import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactMeetingDetectionSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateMode: ((String, String) -> Void)?
    var onRequestUpdatePollSeconds: ((String, Double) -> Void)?
    var onRequestUpdateCooldownMinutes: ((String, Double) -> Void)?
    var onRequestUpdateUseCalendarEnrichment: ((String, Bool) -> Void)?
    var onRequestUpdateRequireCalendarMatch: ((String, Bool) -> Void)?
    var onRequestUpdateAutoEnd: ((String, Bool) -> Void)?
    var onRequestUpdateInactivityTimeoutMinutes: ((String, Double) -> Void)?
    var onRequestUpdateExcludedAppNames: ((String, [String]) -> Void)?
    var onRequestAddExcludedBundleId: ((String, String) -> Void)?
    var onRequestRemoveExcludedBundleId: ((String, String) -> Void)?
    var onRequestAvailableApps: (() -> Void)?
    var onRequestSearchApps: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    private static let allowedModes: Set<String> = ["prompt", "auto_start"]

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactMeetingDetectionSettingsWeakScriptMessageHandler(self),
            name: "basilMeetingDetectionSettingsBridge"
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
                    "[MEETING_DETECTION_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactMeetingDetectionSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilMeetingDetectionSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilMeetingDetectionSettingsBridge",
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
            guard let requestId = body["requestId"] as? String,
                  let mode = body["mode"] as? String,
                  Self.allowedModes.contains(mode) else {
                onMalformedIntent?("requestUpdateMode")
                return
            }
            onRequestUpdateMode?(requestId, mode)
        case "requestUpdatePollSeconds":
            guard let requestId = body["requestId"] as? String, let seconds = (body["pollSeconds"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdatePollSeconds")
                return
            }
            onRequestUpdatePollSeconds?(requestId, seconds)
        case "requestUpdateCooldownMinutes":
            guard let requestId = body["requestId"] as? String, let minutes = (body["cooldownMinutes"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateCooldownMinutes")
                return
            }
            onRequestUpdateCooldownMinutes?(requestId, minutes)
        case "requestUpdateUseCalendarEnrichment":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateUseCalendarEnrichment")
                return
            }
            onRequestUpdateUseCalendarEnrichment?(requestId, enabled)
        case "requestUpdateRequireCalendarMatch":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateRequireCalendarMatch")
                return
            }
            onRequestUpdateRequireCalendarMatch?(requestId, enabled)
        case "requestUpdateAutoEnd":
            guard let requestId = body["requestId"] as? String, let enabled = body["enabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoEnd")
                return
            }
            onRequestUpdateAutoEnd?(requestId, enabled)
        case "requestUpdateInactivityTimeoutMinutes":
            guard let requestId = body["requestId"] as? String, let minutes = (body["minutes"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateInactivityTimeoutMinutes")
                return
            }
            onRequestUpdateInactivityTimeoutMinutes?(requestId, minutes)
        case "requestUpdateExcludedAppNames":
            guard let requestId = body["requestId"] as? String, let names = body["excludedAppNames"] as? [String] else {
                onMalformedIntent?("requestUpdateExcludedAppNames")
                return
            }
            onRequestUpdateExcludedAppNames?(requestId, names)
        case "requestAddExcludedBundleId":
            guard let requestId = body["requestId"] as? String, let bundleId = body["bundleId"] as? String else {
                onMalformedIntent?("requestAddExcludedBundleId")
                return
            }
            onRequestAddExcludedBundleId?(requestId, bundleId)
        case "requestRemoveExcludedBundleId":
            guard let requestId = body["requestId"] as? String, let bundleId = body["bundleId"] as? String else {
                onMalformedIntent?("requestRemoveExcludedBundleId")
                return
            }
            onRequestRemoveExcludedBundleId?(requestId, bundleId)
        case "requestAvailableApps":
            onRequestAvailableApps?()
        case "requestSearchApps":
            guard let requestId = body["requestId"] as? String, let query = body["query"] as? String else {
                onMalformedIntent?("requestSearchApps")
                return
            }
            onRequestSearchApps?(requestId, query)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactMeetingDetectionSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactMeetingDetectionSettingsWebView?

    init(_ target: ReactMeetingDetectionSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
