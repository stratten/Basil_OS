import Foundation
@preconcurrency import WebKit

enum ReactMemorySettingField: String {
    case memoryAfterTaskEnabled
    case memoryDailyEnabled
    case memoryDailyTimeLocal
    case memoryProcessingModel
}

enum ReactMemorySettingValue {
    case bool(Bool)
    case string(String)
    case nullableString(String?)
}

struct ReactMemorySettingPatch {
    let field: ReactMemorySettingField
    let value: ReactMemorySettingValue

    init?(raw: [String: Any]) {
        guard
            let rawField = raw["field"] as? String,
            let field = ReactMemorySettingField(rawValue: rawField)
        else { return nil }
        self.field = field
        switch field {
        case .memoryAfterTaskEnabled, .memoryDailyEnabled:
            guard
                let boolValue = raw["value"] as? NSNumber,
                CFGetTypeID(boolValue) == CFBooleanGetTypeID()
            else { return nil }
            self.value = .bool(boolValue.boolValue)
        case .memoryDailyTimeLocal:
            guard let stringValue = raw["value"] as? String else { return nil }
            self.value = .string(stringValue)
        case .memoryProcessingModel:
            guard raw.keys.contains("value") else { return nil }
            if raw["value"] is NSNull {
                self.value = .nullableString(nil)
            } else if let stringValue = raw["value"] as? String,
                      !stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                self.value = .nullableString(stringValue)
            } else {
                return nil
            }
        }
    }
}

@MainActor
final class ReactMemoryIntelligenceSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onUpdateSetting: ((String, ReactMemorySettingPatch) -> Void)?
    var onRunIntelligenceNow: ((String) -> Void)?
    var onDeclineProposal: ((String, String) -> Void)?
    var onOpenMemoryFile: ((String) -> Void)?
    var onOpenMemoryProposal: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactMemoryIntelligenceSettingsWeakScriptMessageHandler(self),
            name: "basilMemoryIntelligenceSettingsBridge"
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
                DevLogger.shared.error("[MEMORY_INTELLIGENCE_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactMemoryIntelligenceSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilMemoryIntelligenceSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilMemoryIntelligenceSettingsBridge",
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
        case "updateSetting":
            guard
                let requestId = body["requestId"] as? String,
                let patch = ReactMemorySettingPatch(raw: body)
            else {
                onMalformedIntent?("updateSetting")
                return
            }
            onUpdateSetting?(requestId, patch)
        case "runIntelligenceNow":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("runIntelligenceNow")
                return
            }
            onRunIntelligenceNow?(requestId)
        case "declineProposal":
            guard
                let requestId = body["requestId"] as? String,
                let id = body["id"] as? String
            else {
                onMalformedIntent?("declineProposal")
                return
            }
            onDeclineProposal?(requestId, id)
        case "openMemoryFile":
            guard let fileName = body["fileName"] as? String else {
                onMalformedIntent?("openMemoryFile")
                return
            }
            onOpenMemoryFile?(fileName)
        case "openMemoryProposal":
            guard let id = body["id"] as? String else {
                onMalformedIntent?("openMemoryProposal")
                return
            }
            onOpenMemoryProposal?(id)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactMemoryIntelligenceSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactMemoryIntelligenceSettingsWebView?

    init(_ target: ReactMemoryIntelligenceSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
