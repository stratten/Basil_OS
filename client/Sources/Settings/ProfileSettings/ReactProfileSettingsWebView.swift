import Foundation
@preconcurrency import WebKit

struct ReactProfileFieldsPayload {
    let fullName: String?
    let preferredName: String?
    let email: String?
    let jobTitle: String?
    let companyName: String?
    let industry: String?
    let formality: String?
    let tone: String?
    let customInstructions: String?

    init?(raw: [String: Any]) {
        guard let fields = raw["profile"] as? [String: Any] else { return nil }
        func stringOrNil(_ key: String) -> String? {
            guard
                let value = fields[key] as? String,
                !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return nil }
            return value
        }
        fullName = stringOrNil("fullName")
        preferredName = stringOrNil("preferredName")
        email = stringOrNil("email")
        jobTitle = stringOrNil("jobTitle")
        companyName = stringOrNil("companyName")
        industry = stringOrNil("industry")
        formality = (fields["formality"] as? String).flatMap { FormalityLevel(rawValue: $0)?.rawValue }
        tone = (fields["tone"] as? String).flatMap { ToneType(rawValue: $0)?.rawValue }
        customInstructions = stringOrNil("customInstructions")
    }
}

@MainActor
final class ReactProfileSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onSaveProfile: ((String, ReactProfileFieldsPayload) -> Void)?
    var onRequestClearProfile: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactProfileSettingsWeakScriptMessageHandler(self),
            name: "basilProfileSettingsBridge"
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
                DevLogger.shared.error("[PROFILE_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactProfileSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilProfileSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilProfileSettingsBridge",
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
        case "saveProfile":
            guard
                let requestId = body["requestId"] as? String,
                let payload = ReactProfileFieldsPayload(raw: body)
            else {
                onMalformedIntent?("saveProfile")
                return
            }
            onSaveProfile?(requestId, payload)
        case "requestClearProfile":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestClearProfile")
                return
            }
            onRequestClearProfile?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactProfileSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactProfileSettingsWebView?

    init(_ target: ReactProfileSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
