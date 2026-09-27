import Foundation
@preconcurrency import WebKit

enum ReactHomeQuickToggleField: String {
    case enableMonitoringAtStartup
    case enableVoiceListenerAtStartup
    case startActivityCaptureAtLaunch
    case startMeetingDetectionAtLaunch
    case activityCaptureEnabled
    case meetingDetectionEnabled
    case proactiveSuggestionsEnabled
}

@MainActor
final class ReactHomeSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onUpdateToggle: ((String, ReactHomeQuickToggleField, Bool) -> Void)?
    var onUpdateSelectedModel: ((String, String) -> Void)?
    var onUpdateSelectedTranscriptionModel: ((String, String) -> Void)?
    var onOpenSetupAssistant: ((String) -> Void)?
    var onOpenPowerUserGuide: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactHomeSettingsWeakScriptMessageHandler(self),
            name: "basilHomeSettingsBridge"
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
                DevLogger.shared.error("[HOME_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactHomeSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilHomeSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilHomeSettingsBridge",
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
        case "updateToggle":
            guard
                let requestId = body["requestId"] as? String,
                let rawField = body["field"] as? String,
                let field = ReactHomeQuickToggleField(rawValue: rawField),
                let value = (body["value"] as? NSNumber)?.boolValue
            else {
                onMalformedIntent?("updateToggle")
                return
            }
            onUpdateToggle?(requestId, field, value)
        case "updateSelectedModel":
            guard
                let requestId = body["requestId"] as? String,
                let modelId = body["modelId"] as? String
            else {
                onMalformedIntent?("updateSelectedModel")
                return
            }
            onUpdateSelectedModel?(requestId, modelId)
        case "updateSelectedTranscriptionModel":
            guard
                let requestId = body["requestId"] as? String,
                let modelId = body["modelId"] as? String
            else {
                onMalformedIntent?("updateSelectedTranscriptionModel")
                return
            }
            onUpdateSelectedTranscriptionModel?(requestId, modelId)
        case "openSetupAssistant":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("openSetupAssistant")
                return
            }
            onOpenSetupAssistant?(requestId)
        case "openPowerUserGuide":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("openPowerUserGuide")
                return
            }
            onOpenPowerUserGuide?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactHomeSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactHomeSettingsWebView?

    init(_ target: ReactHomeSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
