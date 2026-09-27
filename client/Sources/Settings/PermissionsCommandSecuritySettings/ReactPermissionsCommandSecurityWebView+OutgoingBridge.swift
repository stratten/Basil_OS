import Foundation

@MainActor
protocol ReactPermissionsCommandSecurityBridgeOutput: AnyObject {
    func sendInit(viewModel: PermissionsSettingsViewModel)
    func sendSnapshot(viewModel: PermissionsSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactPermissionsCommandSecurityWebView: ReactPermissionsCommandSecurityBridgeOutput {
    func sendInit(viewModel: PermissionsSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilPermissionsCommandSecurity && window.basilPermissionsCommandSecurity.onEvent", args: event)
    }

    func sendSnapshot(viewModel: PermissionsSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilPermissionsCommandSecurity && window.basilPermissionsCommandSecurity.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilPermissionsCommandSecurity && window.basilPermissionsCommandSecurity.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilPermissionsCommandSecurity && window.basilPermissionsCommandSecurity.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel: PermissionsSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "isLoading": viewModel.isLoading,
            "error": viewModel.errorMessage as Any? ?? NSNull(),
            "approvalSettings": viewModel.approvalSettings.map(Self.approvalSettingsPayload) as Any? ?? NSNull(),
            "whitelistPatterns": viewModel.whitelistPatterns.map(Self.whitelistPatternPayload),
        ]
    }

    private static func approvalSettingsPayload(_ settings: ExecutionApprovalSettings) -> [String: Any] {
        [
            "approvalMode": settings.approvalMode.rawValue,
            "showFullCommandInPrompt": settings.showFullCommandInPrompt,
            "rememberChoiceOption": settings.rememberChoiceOption,
            "autoApproveReadOnly": settings.autoApproveReadOnly,
            "blockDangerousPatterns": settings.blockDangerousPatterns,
            "whitelistedCount": settings.whitelistedCount,
            "safeExecutionMode": settings.safeExecutionMode,
            "approvalTimeoutSeconds": settings.approvalTimeoutSeconds,
            "timeoutBehavior": settings.timeoutBehavior.rawValue,
        ]
    }

    private static func whitelistPatternPayload(_ pattern: WhitelistPattern) -> [String: Any] {
        let isoFormatter = ISO8601DateFormatter()
        return [
            "id": pattern.id,
            "pattern": pattern.pattern,
            "patternType": pattern.patternType,
            "description": pattern.description,
            "addedDate": pattern.addedDate.map(isoFormatter.string) as Any? ?? NSNull(),
            "lastUsed": pattern.lastUsed.map(isoFormatter.string) as Any? ?? NSNull(),
            "useCount": pattern.useCount,
            "riskLevel": pattern.riskLevel,
        ]
    }
}
