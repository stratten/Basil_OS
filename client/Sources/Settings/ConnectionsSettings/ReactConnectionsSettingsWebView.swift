import Foundation
@preconcurrency import WebKit

@MainActor
final class ReactConnectionsSettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onRequestStartOAuth: ((String, String, String, String?) -> Void)?
    var onRequestStartSlackOAuth: ((String, String, String, String?) -> Void)?
    var onRequestStartGitHubDeviceFlow: ((String, String, String, String?) -> Void)?
    var onRequestCancelGitHubDeviceFlow: ((String) -> Void)?
    var onRequestOpenExternalUrl: ((String, String) -> Void)?
    var onRequestRegisterManualToken: ((String, String, String, String?, String) -> Void)?
    var onRequestDeleteConnection: ((String, String) -> Void)?
    var onRequestRefreshTools: ((String, String) -> Void)?
    var onRequestUpdateConnectionMetadata: ((String, String, String, String?) -> Void)?
    var onRequestCheckConnectionStatus: ((String, String) -> Void)?
    var onRequestReconnectConnection: ((String, String) -> Void)?
    var onRequestReplaceConnectionToken: ((String, String, String) -> Void)?
    var onRequestUpdatePolicy: ((String, String, String, String) -> Void)?
    var onRequestRefreshCallLog: ((String) -> Void)?
    var onRequestCreateProviderProfile: ((String, String, [String], [String], String?, String?, [String]) -> Void)?
    var onRequestUpdateProviderProfile: ((String, String, Int, String, [String], [String], String?, String?, [String]) -> Void)?
    var onRequestSetProviderProfileEnabled: ((String, String, Int, Bool) -> Void)?
    var onRequestRemoveProviderProfile: ((String, String, Int) -> Void)?
    var onRequestLoadProviderProfileConfiguration: ((String, String) -> Void)?
    var onRequestChooseWorkspaceFolder: ((String, String) -> Void)?
    var onRequestCreateWorkspaceGrant: ((String, String, String, String, String?, [String]) -> Void)?
    var onRequestUpdateWorkspaceGrant: ((String, String, String, Int, String, String?, [String]) -> Void)?
    var onRequestRevokeWorkspaceGrant: ((String, String, String, Int) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            ReactConnectionsSettingsWeakScriptMessageHandler(self),
            name: "basilConnectionsSettingsBridge"
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
                    "[CONNECTIONS_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)",
                    context: "ReactConnectionsSettingsWebView"
                )
                #endif
            }
        }
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilConnectionsSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilConnectionsSettingsBridge",
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
        case "requestStartOAuth":
            guard let requestId = body["requestId"] as? String,
                  let serverUrl = body["serverUrl"] as? String,
                  let friendlyName = body["friendlyName"] as? String else {
                onMalformedIntent?("requestStartOAuth")
                return
            }
            onRequestStartOAuth?(requestId, serverUrl, friendlyName, body["description"] as? String)
        case "requestStartSlackOAuth":
            guard let requestId = body["requestId"] as? String,
                  let serverUrl = body["serverUrl"] as? String,
                  let friendlyName = body["friendlyName"] as? String else {
                onMalformedIntent?("requestStartSlackOAuth")
                return
            }
            onRequestStartSlackOAuth?(requestId, serverUrl, friendlyName, body["description"] as? String)
        case "requestStartGitHubDeviceFlow":
            guard let requestId = body["requestId"] as? String,
                  let serverUrl = body["serverUrl"] as? String,
                  let friendlyName = body["friendlyName"] as? String else {
                onMalformedIntent?("requestStartGitHubDeviceFlow")
                return
            }
            onRequestStartGitHubDeviceFlow?(requestId, serverUrl, friendlyName, body["description"] as? String)
        case "requestCancelGitHubDeviceFlow":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestCancelGitHubDeviceFlow")
                return
            }
            onRequestCancelGitHubDeviceFlow?(requestId)
        case "requestOpenExternalUrl":
            guard let requestId = body["requestId"] as? String,
                  let url = body["url"] as? String else {
                onMalformedIntent?("requestOpenExternalUrl")
                return
            }
            onRequestOpenExternalUrl?(requestId, url)
        case "requestRegisterManualToken":
            guard let requestId = body["requestId"] as? String,
                  let serverUrl = body["serverUrl"] as? String,
                  let friendlyName = body["friendlyName"] as? String,
                  let bearerToken = body["bearerToken"] as? String else {
                onMalformedIntent?("requestRegisterManualToken")
                return
            }
            onRequestRegisterManualToken?(requestId, serverUrl, friendlyName, body["description"] as? String, bearerToken)
        case "requestDeleteConnection":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String else {
                onMalformedIntent?("requestDeleteConnection")
                return
            }
            onRequestDeleteConnection?(requestId, connectionId)
        case "requestRefreshTools":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String else {
                onMalformedIntent?("requestRefreshTools")
                return
            }
            onRequestRefreshTools?(requestId, connectionId)
        case "requestUpdateConnectionMetadata":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String,
                  let friendlyName = body["friendlyName"] as? String else {
                onMalformedIntent?("requestUpdateConnectionMetadata")
                return
            }
            onRequestUpdateConnectionMetadata?(requestId, connectionId, friendlyName, body["description"] as? String)
        case "requestCheckConnectionStatus":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String else {
                onMalformedIntent?("requestCheckConnectionStatus")
                return
            }
            onRequestCheckConnectionStatus?(requestId, connectionId)
        case "requestReconnectConnection":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String else {
                onMalformedIntent?("requestReconnectConnection")
                return
            }
            onRequestReconnectConnection?(requestId, connectionId)
        case "requestReplaceConnectionToken":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String,
                  let bearerToken = body["bearerToken"] as? String else {
                onMalformedIntent?("requestReplaceConnectionToken")
                return
            }
            onRequestReplaceConnectionToken?(requestId, connectionId, bearerToken)
        case "requestUpdatePolicy":
            guard let requestId = body["requestId"] as? String,
                  let connectionId = body["connectionId"] as? String,
                  let toolName = body["toolName"] as? String,
                  let policy = body["policy"] as? String else {
                onMalformedIntent?("requestUpdatePolicy")
                return
            }
            onRequestUpdatePolicy?(requestId, connectionId, toolName, policy)
        case "requestRefreshCallLog":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("requestRefreshCallLog")
                return
            }
            onRequestRefreshCallLog?(requestId)
        case "requestCreateProviderProfile":
            guard let requestId = body["requestId"] as? String,
                  let displayName = body["displayName"] as? String,
                  let launchArgv = body["launchArgv"] as? [String],
                  let environmentAllowlist = body["environmentAllowlist"] as? [String],
                  let routingHints = body["routingHints"] as? [String] else {
                onMalformedIntent?("requestCreateProviderProfile")
                return
            }
            onRequestCreateProviderProfile?(requestId, displayName, launchArgv, environmentAllowlist, body["authenticationMethodId"] as? String, body["description"] as? String, routingHints)
        case "requestUpdateProviderProfile":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let expectedRevision = (body["expectedRevision"] as? NSNumber)?.intValue,
                  let displayName = body["displayName"] as? String,
                  let launchArgv = body["launchArgv"] as? [String],
                  let environmentAllowlist = body["environmentAllowlist"] as? [String],
                  let routingHints = body["routingHints"] as? [String] else {
                onMalformedIntent?("requestUpdateProviderProfile")
                return
            }
            onRequestUpdateProviderProfile?(requestId, profileId, expectedRevision, displayName, launchArgv, environmentAllowlist, body["authenticationMethodId"] as? String, body["description"] as? String, routingHints)
        case "requestSetProviderProfileEnabled":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let expectedRevision = (body["expectedRevision"] as? NSNumber)?.intValue,
                  let enabled = (body["enabled"] as? NSNumber)?.boolValue else {
                onMalformedIntent?("requestSetProviderProfileEnabled")
                return
            }
            onRequestSetProviderProfileEnabled?(requestId, profileId, expectedRevision, enabled)
        case "requestRemoveProviderProfile":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let expectedRevision = (body["expectedRevision"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestRemoveProviderProfile")
                return
            }
            onRequestRemoveProviderProfile?(requestId, profileId, expectedRevision)
        case "requestLoadProviderProfileConfiguration":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String else {
                onMalformedIntent?("requestLoadProviderProfileConfiguration")
                return
            }
            onRequestLoadProviderProfileConfiguration?(requestId, profileId)
        case "requestChooseWorkspaceFolder":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String else {
                onMalformedIntent?("requestChooseWorkspaceFolder")
                return
            }
            onRequestChooseWorkspaceFolder?(requestId, profileId)
        case "requestCreateWorkspaceGrant":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let canonicalWorkspaceRoot = body["canonicalWorkspaceRoot"] as? String,
                  let workspaceLabel = body["workspaceLabel"] as? String,
                  let routingHints = body["routingHints"] as? [String] else {
                onMalformedIntent?("requestCreateWorkspaceGrant")
                return
            }
            onRequestCreateWorkspaceGrant?(requestId, profileId, canonicalWorkspaceRoot, workspaceLabel, body["description"] as? String, routingHints)
        case "requestUpdateWorkspaceGrant":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let grantId = body["grantId"] as? String,
                  let expectedRevision = (body["expectedRevision"] as? NSNumber)?.intValue,
                  let workspaceLabel = body["workspaceLabel"] as? String,
                  let routingHints = body["routingHints"] as? [String] else {
                onMalformedIntent?("requestUpdateWorkspaceGrant")
                return
            }
            onRequestUpdateWorkspaceGrant?(requestId, profileId, grantId, expectedRevision, workspaceLabel, body["description"] as? String, routingHints)
        case "requestRevokeWorkspaceGrant":
            guard let requestId = body["requestId"] as? String,
                  let profileId = body["profileId"] as? String,
                  let grantId = body["grantId"] as? String,
                  let expectedRevision = (body["expectedRevision"] as? NSNumber)?.intValue else {
                onMalformedIntent?("requestRevokeWorkspaceGrant")
                return
            }
            onRequestRevokeWorkspaceGrant?(requestId, profileId, grantId, expectedRevision)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactConnectionsSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactConnectionsSettingsWebView?

    init(_ target: ReactConnectionsSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
