import Foundation
@preconcurrency import WebKit

/// Bridge-facing mirror of `ZettelSettingsData` decoded with default
/// (camelCase) CodingKeys, since the JS message body's keys match this
/// struct's Swift property names directly rather than the snake_case the
/// HTTP layer's `ZettelSettingsData.CodingKeys` expects.
struct ReactMemoriesSettingsFields: Codable {
    var enabledSources: [String]
    var historyDays: Int
    var cardingEnabled: Bool
    var cardingIntervalMinutes: Int
    var limitPerSourcePerPass: Int
    var narrativeEnabled: Bool
    var narrativeModel: String
    var narrativeMode: String
    var narrativeScheduledTime: String
    var narrativeIntervalMinutes: Int
    var narrativeBatchSize: Int
    var narrativeMaxAttempts: Int
    var narrativeMaxRecords: Int

    var asZettelSettingsData: ZettelSettingsData {
        ZettelSettingsData(
            enabledSources: enabledSources,
            historyDays: historyDays,
            cardingEnabled: cardingEnabled,
            cardingIntervalMinutes: cardingIntervalMinutes,
            limitPerSourcePerPass: limitPerSourcePerPass,
            narrativeEnabled: narrativeEnabled,
            narrativeModel: narrativeModel,
            narrativeMode: narrativeMode,
            narrativeScheduledTime: narrativeScheduledTime,
            narrativeIntervalMinutes: narrativeIntervalMinutes,
            narrativeBatchSize: narrativeBatchSize,
            narrativeMaxAttempts: narrativeMaxAttempts,
            narrativeMaxRecords: narrativeMaxRecords
        )
    }

    init(from zettel: ZettelSettingsData) {
        enabledSources = zettel.enabledSources
        historyDays = zettel.historyDays
        cardingEnabled = zettel.cardingEnabled
        cardingIntervalMinutes = zettel.cardingIntervalMinutes
        limitPerSourcePerPass = zettel.limitPerSourcePerPass
        narrativeEnabled = zettel.narrativeEnabled
        narrativeModel = zettel.narrativeModel
        narrativeMode = zettel.narrativeMode
        narrativeScheduledTime = zettel.narrativeScheduledTime
        narrativeIntervalMinutes = zettel.narrativeIntervalMinutes
        narrativeBatchSize = zettel.narrativeBatchSize
        narrativeMaxAttempts = zettel.narrativeMaxAttempts
        narrativeMaxRecords = zettel.narrativeMaxRecords
    }

    init?(raw: Any?) {
        guard let raw,
              let data = try? JSONSerialization.data(withJSONObject: raw),
              let decoded = try? JSONDecoder().decode(ReactMemoriesSettingsFields.self, from: data)
        else { return nil }
        self = decoded
    }
}

@MainActor
final class ReactMemoriesSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateSettings: ((String, ReactMemoriesSettingsFields) -> Void)?
    var onRequestCollectNow: ((String) -> Void)?
    var onRequestSummarizeNow: ((String) -> Void)?
    var onRequestRetryFailedSummaries: ((String) -> Void)?
    var onRequestCancelSummarize: ((String) -> Void)?
    var onRequestRefreshStats: ((String) -> Void)?
    var onRequestNarrativeProgress: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactMemoriesSettingsWeakScriptMessageHandler(self),
            name: "basilMemoriesSettingsBridge"
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
                DevLogger.shared.error("[MEMORIES_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactMemoriesSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilMemoriesSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilMemoriesSettingsBridge",
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
            guard
                let requestId = body["requestId"] as? String,
                let fields = ReactMemoriesSettingsFields(raw: body["settings"])
            else {
                onMalformedIntent?("requestUpdateSettings")
                return
            }
            onRequestUpdateSettings?(requestId, fields)
        case "requestCollectNow":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestCollectNow")
                return
            }
            onRequestCollectNow?(requestId)
        case "requestSummarizeNow":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestSummarizeNow")
                return
            }
            onRequestSummarizeNow?(requestId)
        case "requestRetryFailedSummaries":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestRetryFailedSummaries")
                return
            }
            onRequestRetryFailedSummaries?(requestId)
        case "requestCancelSummarize":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestCancelSummarize")
                return
            }
            onRequestCancelSummarize?(requestId)
        case "requestRefreshStats":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestRefreshStats")
                return
            }
            onRequestRefreshStats?(requestId)
        case "requestNarrativeProgress":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestNarrativeProgress")
                return
            }
            onRequestNarrativeProgress?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactMemoriesSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactMemoriesSettingsWebView?

    init(_ target: ReactMemoriesSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
