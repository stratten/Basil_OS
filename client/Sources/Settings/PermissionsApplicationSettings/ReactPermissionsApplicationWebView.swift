import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactPermissionsApplicationWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestPermissionStatus: ((String) -> Void)?
    var onRequestPermission: ((String, String) -> Void)?
    var onOpenSystemSettings: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactPermissionsApplicationWeakScriptMessageHandler(self),
            name: "basilPermissionsApplicationBridge"
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
                    "[PERMISSIONS_APPLICATION_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactPermissionsApplicationWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilPermissionsApplicationBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilPermissionsApplicationBridge",
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
        case "requestPermissionStatus":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestPermissionStatus")
                return
            }
            onRequestPermissionStatus?(requestId)
        case "requestPermission":
            guard let requestId = body["requestId"] as? String, let kind = body["kind"] as? String else {
                onMalformedIntent?("requestPermission")
                return
            }
            onRequestPermission?(requestId, kind)
        case "openSystemSettings":
            guard let requestId = body["requestId"] as? String, let kind = body["kind"] as? String else {
                onMalformedIntent?("openSystemSettings")
                return
            }
            onOpenSystemSettings?(requestId, kind)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactPermissionsApplicationWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactPermissionsApplicationWebView?

    init(_ target: ReactPermissionsApplicationWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
