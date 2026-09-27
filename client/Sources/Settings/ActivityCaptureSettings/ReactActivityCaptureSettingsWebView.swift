import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactActivityCaptureSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateFrequencySeconds: ((String, Int) -> Void)?
    var onRequestUpdateIdleThresholdSeconds: ((String, Double) -> Void)?
    var onRequestUpdatePostWakeGraceSeconds: ((String, Double) -> Void)?
    var onRequestAddExcludedBundleId: ((String, String) -> Void)?
    var onRequestRemoveExcludedBundleId: ((String, String) -> Void)?
    var onRequestAvailableApps: (() -> Void)?
    var onRequestSearchApps: ((String, String) -> Void)?
    var onRequestUpdateProcessingModel: ((String, String) -> Void)?
    var onRequestUpdateProcessingMode: ((String, String) -> Void)?
    var onRequestUpdateScheduledProcessingTime: ((String, String) -> Void)?
    var onRequestUpdateProcessingMaxRecords: ((String, Int) -> Void)?
    var onRequestUpdateAutoCleanupEnabled: ((String, Bool) -> Void)?
    var onRequestUpdateRetentionDays: ((String, Int) -> Void)?
    var onRequestUpdateCleanupTime: ((String, Int, Int) -> Void)?
    var onRequestUpdateMaxStorageMb: ((String, Int) -> Void)?
    var onRequestTestCapture: ((String) -> Void)?
    var onRequestProcessBacklog: ((String) -> Void)?
    var onRequestCancelProcessing: ((String) -> Void)?
    var onRequestClearBacklog: ((String) -> Void)?
    var onRequestClearAllCaptures: ((String) -> Void)?
    var onRequestStatus: (() -> Void)?
    var onRequestProcessingProgress: ((String?) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactActivityCaptureSettingsWeakScriptMessageHandler(self),
            name: "basilActivityCaptureSettingsBridge"
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
                    "[ACTIVITY_CAPTURE_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactActivityCaptureSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilActivityCaptureSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilActivityCaptureSettingsBridge",
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
        case "requestUpdateFrequencySeconds":
            guard let requestId = body["requestId"] as? String, let seconds = (body["frequencySeconds"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateFrequencySeconds")
                return
            }
            onRequestUpdateFrequencySeconds?(requestId, seconds)
        case "requestUpdateIdleThresholdSeconds":
            guard let requestId = body["requestId"] as? String, let seconds = (body["idleThresholdSeconds"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdateIdleThresholdSeconds")
                return
            }
            onRequestUpdateIdleThresholdSeconds?(requestId, seconds)
        case "requestUpdatePostWakeGraceSeconds":
            guard let requestId = body["requestId"] as? String, let seconds = (body["postWakeGraceSeconds"] as? NSNumber)?.doubleValue else {
                onMalformedIntent?("requestUpdatePostWakeGraceSeconds")
                return
            }
            onRequestUpdatePostWakeGraceSeconds?(requestId, seconds)
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
        case "requestUpdateProcessingModel":
            guard let requestId = body["requestId"] as? String, let modelId = body["processingModel"] as? String else {
                onMalformedIntent?("requestUpdateProcessingModel")
                return
            }
            onRequestUpdateProcessingModel?(requestId, modelId)
        case "requestUpdateProcessingMode":
            guard let requestId = body["requestId"] as? String, let mode = body["processingMode"] as? String else {
                onMalformedIntent?("requestUpdateProcessingMode")
                return
            }
            onRequestUpdateProcessingMode?(requestId, mode)
        case "requestUpdateScheduledProcessingTime":
            guard let requestId = body["requestId"] as? String, let time = body["scheduledProcessingTime"] as? String else {
                onMalformedIntent?("requestUpdateScheduledProcessingTime")
                return
            }
            onRequestUpdateScheduledProcessingTime?(requestId, time)
        case "requestUpdateProcessingMaxRecords":
            guard let requestId = body["requestId"] as? String, let value = (body["processingMaxRecords"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateProcessingMaxRecords")
                return
            }
            onRequestUpdateProcessingMaxRecords?(requestId, value)
        case "requestUpdateAutoCleanupEnabled":
            guard let requestId = body["requestId"] as? String, let enabled = body["autoCleanupEnabled"] as? Bool else {
                onMalformedIntent?("requestUpdateAutoCleanupEnabled")
                return
            }
            onRequestUpdateAutoCleanupEnabled?(requestId, enabled)
        case "requestUpdateRetentionDays":
            guard let requestId = body["requestId"] as? String, let days = (body["retentionDays"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateRetentionDays")
                return
            }
            onRequestUpdateRetentionDays?(requestId, days)
        case "requestUpdateCleanupTime":
            guard let requestId = body["requestId"] as? String,
                  let hour = (body["cleanupHour"] as? NSNumber)?.intValue,
                  let minute = (body["cleanupMinute"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateCleanupTime")
                return
            }
            onRequestUpdateCleanupTime?(requestId, hour, minute)
        case "requestUpdateMaxStorageMb":
            guard let requestId = body["requestId"] as? String, let mb = (body["maxStorageMb"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestUpdateMaxStorageMb")
                return
            }
            onRequestUpdateMaxStorageMb?(requestId, mb)
        case "requestTestCapture":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestTestCapture")
                return
            }
            onRequestTestCapture?(requestId)
        case "requestProcessBacklog":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestProcessBacklog")
                return
            }
            onRequestProcessBacklog?(requestId)
        case "requestCancelProcessing":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestCancelProcessing")
                return
            }
            onRequestCancelProcessing?(requestId)
        case "requestClearBacklog":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestClearBacklog")
                return
            }
            onRequestClearBacklog?(requestId)
        case "requestClearAllCaptures":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestClearAllCaptures")
                return
            }
            onRequestClearAllCaptures?(requestId)
        case "requestStatus":
            onRequestStatus?()
        case "requestProcessingProgress":
            onRequestProcessingProgress?(body["requestId"] as? String)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactActivityCaptureSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactActivityCaptureSettingsWebView?

    init(_ target: ReactActivityCaptureSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
