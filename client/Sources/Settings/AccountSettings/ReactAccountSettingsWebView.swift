import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactAccountSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestLogin: ((String, String, String) -> Void)?
    var onRequestSignup: ((String, String, String, String) -> Void)?
    var onRequestGoogleSignIn: ((String) -> Void)?
    var onRequestSignOut: ((String) -> Void)?
    var onRequestSetApiKeyPreference: ((String, String) -> Void)?
    var onRequestPaymentSetup: ((String) -> Void)?
    var onRequestRefreshPaymentAndUsage: ((String) -> Void)?
    var onRequestDeleteAccount: ((String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactAccountSettingsWeakScriptMessageHandler(self),
            name: "basilAccountSettingsBridge"
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
                    "[ACCOUNT_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactAccountSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilAccountSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilAccountSettingsBridge",
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
        case "requestLogin":
            guard let requestId = body["requestId"] as? String,
                  let email = body["email"] as? String,
                  let password = body["password"] as? String else {
                onMalformedIntent?("requestLogin")
                return
            }
            onRequestLogin?(requestId, email, password)
        case "requestSignup":
            guard let requestId = body["requestId"] as? String,
                  let email = body["email"] as? String,
                  let password = body["password"] as? String,
                  let confirmPassword = body["confirmPassword"] as? String else {
                onMalformedIntent?("requestSignup")
                return
            }
            onRequestSignup?(requestId, email, password, confirmPassword)
        case "requestGoogleSignIn":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestGoogleSignIn")
                return
            }
            onRequestGoogleSignIn?(requestId)
        case "requestSignOut":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestSignOut")
                return
            }
            onRequestSignOut?(requestId)
        case "requestSetApiKeyPreference":
            guard let requestId = body["requestId"] as? String,
                  let preference = body["preference"] as? String else {
                onMalformedIntent?("requestSetApiKeyPreference")
                return
            }
            onRequestSetApiKeyPreference?(requestId, preference)
        case "requestPaymentSetup":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestPaymentSetup")
                return
            }
            onRequestPaymentSetup?(requestId)
        case "requestRefreshPaymentAndUsage":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestRefreshPaymentAndUsage")
                return
            }
            onRequestRefreshPaymentAndUsage?(requestId)
        case "requestDeleteAccount":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestDeleteAccount")
                return
            }
            onRequestDeleteAccount?(requestId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactAccountSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactAccountSettingsWebView?

    init(_ target: ReactAccountSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
