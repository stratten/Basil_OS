import Foundation
@preconcurrency import WebKit

struct ReactMacContactsSettingsUpdateRequest {
    let requestId: String
    let enabled: Bool

    init?(raw: [String: Any]) {
        guard
            let requestId = raw["requestId"] as? String,
            !requestId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            let enabled = raw["enabled"] as? Bool
        else {
            return nil
        }
        self.requestId = requestId
        self.enabled = enabled
    }
}

@MainActor
final class ReactMacContactsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onUpdateEnabled: ((ReactMacContactsSettingsUpdateRequest) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactMacContactsSettingsWeakScriptMessageHandler(self),
            name: "basilMacContactsSettingsBridge"
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
                DevLogger.shared.error("[MAC_CONTACTS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactMacContactsSettingsWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilMacContactsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilMacContactsSettingsBridge",
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
        case "updateEnabled":
            guard let request = ReactMacContactsSettingsUpdateRequest(raw: body) else {
                onMalformedIntent?("updateEnabled")
                return
            }
            onUpdateEnabled?(request)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactMacContactsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactMacContactsSettingsWebView?

    init(_ target: ReactMacContactsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
