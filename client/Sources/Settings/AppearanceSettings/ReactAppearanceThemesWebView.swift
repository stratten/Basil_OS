import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactAppearanceThemesWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onSaveTheme: ((String, ReactAppearanceThemeSavePayload) -> Void)?
    var onDeleteTheme: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?
    var onRejectedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactAppearanceThemesWeakScriptMessageHandler(self),
            name: "basilAppearanceThemesBridge"
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
                DevLogger.shared.error("[APPEARANCE_THEMES_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactAppearanceThemesWebView")
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilAppearanceThemesBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilAppearanceThemesBridge",
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
        case "saveTheme":
            guard
                let requestId = body["requestId"] as? String,
                let rawTheme = body["theme"] as? [String: Any],
                let payload = ReactAppearanceThemeSavePayload(raw: rawTheme)
            else {
                if let requestId = body["requestId"] as? String {
                    onRejectedIntent?(requestId)
                }
                onMalformedIntent?("saveTheme")
                return
            }
            onSaveTheme?(requestId, payload)
        case "deleteTheme":
            guard
                let requestId = body["requestId"] as? String,
                let themeId = body["themeId"] as? String,
                CustomAppearanceThemeLimits.isValidThemeID(themeId)
            else {
                if let requestId = body["requestId"] as? String {
                    onRejectedIntent?(requestId)
                }
                onMalformedIntent?("deleteTheme")
                return
            }
            onDeleteTheme?(requestId, themeId)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactAppearanceThemesWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactAppearanceThemesWebView?

    init(_ target: ReactAppearanceThemesWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
