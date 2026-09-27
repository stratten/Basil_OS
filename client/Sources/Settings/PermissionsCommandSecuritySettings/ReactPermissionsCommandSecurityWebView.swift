import Foundation
@preconcurrency import WebKit

struct PermissionsCommandSecurityPatch {
    let approvalMode: String?
    let safeExecutionMode: Bool?
    let autoApproveReadOnly: Bool?
    let blockDangerousPatterns: Bool?
    let approvalTimeoutSeconds: Int?
    let timeoutBehavior: String?

    init?(payload: [String: Any]?) {
        guard let payload else { return nil }
        approvalMode = payload["approvalMode"] as? String
        safeExecutionMode = (payload["safeExecutionMode"] as? NSNumber)?.boolValue
        autoApproveReadOnly = (payload["autoApproveReadOnly"] as? NSNumber)?.boolValue
        blockDangerousPatterns = (payload["blockDangerousPatterns"] as? NSNumber)?.boolValue
        if let timeoutValue = payload["approvalTimeoutSeconds"] as? NSNumber {
            guard timeoutValue.doubleValue.rounded(.towardZero) == timeoutValue.doubleValue else { return nil }
            approvalTimeoutSeconds = timeoutValue.intValue
        } else {
            approvalTimeoutSeconds = nil
        }
        timeoutBehavior = payload["timeoutBehavior"] as? String
    }

    var isEmpty: Bool {
        approvalMode == nil
            && safeExecutionMode == nil
            && autoApproveReadOnly == nil
            && blockDangerousPatterns == nil
            && approvalTimeoutSeconds == nil
            && timeoutBehavior == nil
    }

    func updateRequest() -> UpdateApprovalSettingsRequest {
        UpdateApprovalSettingsRequest(
            approvalMode: approvalMode,
            autoApproveReadOnly: autoApproveReadOnly,
            blockDangerousPatterns: blockDangerousPatterns,
            safeExecutionMode: safeExecutionMode,
            approvalTimeoutSeconds: approvalTimeoutSeconds,
            timeoutBehavior: timeoutBehavior
        )
    }
}

@MainActor
final class ReactPermissionsCommandSecurityWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestUpdateApprovalSetting: ((String, PermissionsCommandSecurityPatch) -> Void)?
    var onRequestAddWhitelistPattern: ((String, String, String, String) -> Void)?
    var onRequestUpdateWhitelistPattern: ((String, String, String, String, String) -> Void)?
    var onRequestDeleteWhitelistPattern: ((String, String) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactPermissionsCommandSecurityWeakScriptMessageHandler(self),
            name: "basilPermissionsCommandSecurityBridge"
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
                    "[PERMISSIONS_COMMAND_SECURITY_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactPermissionsCommandSecurityWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilPermissionsCommandSecurityBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilPermissionsCommandSecurityBridge",
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
        case "requestUpdateApprovalSetting":
            guard let requestId = body["requestId"] as? String,
                  let patch = PermissionsCommandSecurityPatch(payload: body["patch"] as? [String: Any]) else {
                onMalformedIntent?("requestUpdateApprovalSetting")
                return
            }
            onRequestUpdateApprovalSetting?(requestId, patch)
        case "requestAddWhitelistPattern":
            guard let requestId = body["requestId"] as? String,
                  let pattern = body["pattern"] as? String,
                  let patternType = body["patternType"] as? String else {
                onMalformedIntent?("requestAddWhitelistPattern")
                return
            }
            onRequestAddWhitelistPattern?(requestId, pattern, patternType, body["description"] as? String ?? "")
        case "requestUpdateWhitelistPattern":
            guard let requestId = body["requestId"] as? String,
                  let id = body["id"] as? String,
                  let pattern = body["pattern"] as? String,
                  let patternType = body["patternType"] as? String else {
                onMalformedIntent?("requestUpdateWhitelistPattern")
                return
            }
            onRequestUpdateWhitelistPattern?(requestId, id, pattern, patternType, body["description"] as? String ?? "")
        case "requestDeleteWhitelistPattern":
            guard let requestId = body["requestId"] as? String, let id = body["id"] as? String else {
                onMalformedIntent?("requestDeleteWhitelistPattern")
                return
            }
            onRequestDeleteWhitelistPattern?(requestId, id)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactPermissionsCommandSecurityWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactPermissionsCommandSecurityWebView?

    init(_ target: ReactPermissionsCommandSecurityWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
