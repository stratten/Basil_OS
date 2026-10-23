import Foundation

@MainActor
protocol ReactConnectionsSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: ConnectionsSettingsViewModel, providerProfilesViewModel: ProviderProfilesViewModel)
    func sendSnapshot(viewModel: ConnectionsSettingsViewModel, providerProfilesViewModel: ProviderProfilesViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
    func sendProviderProfileConfiguration(requestId: String, configuration: APIClient.ProviderProfileConfiguration?, errorMessage: String?)
    func sendWorkspaceFolderChosen(requestId: String, profileId: String, canonicalWorkspaceRoot: String?, errorMessage: String?)
}

extension ReactConnectionsSettingsWebView: ReactConnectionsSettingsBridgeOutput {
    func sendInit(viewModel: ConnectionsSettingsViewModel, providerProfilesViewModel: ProviderProfilesViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel, providerProfilesViewModel: providerProfilesViewModel)
        event["protocolVersion"] = 1
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: ConnectionsSettingsViewModel, providerProfilesViewModel: ProviderProfilesViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel, providerProfilesViewModel: providerProfilesViewModel)
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    func sendProviderProfileConfiguration(requestId: String, configuration: APIClient.ProviderProfileConfiguration?, errorMessage: String?) {
        var event: [String: Any] = [
            "type": "providerProfileConfiguration",
            "requestId": requestId,
            "configuration": configuration.map { providerProfileConfigurationPayload($0) } as Any,
        ]
        if let errorMessage {
            event["errorMessage"] = errorMessage
        }
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    func sendWorkspaceFolderChosen(requestId: String, profileId: String, canonicalWorkspaceRoot: String?, errorMessage: String?) {
        var event: [String: Any] = [
            "type": "workspaceFolderChosen",
            "requestId": requestId,
            "profileId": profileId,
            "canonicalWorkspaceRoot": canonicalWorkspaceRoot as Any,
        ]
        if let errorMessage {
            event["errorMessage"] = errorMessage
        }
        callJS("window.basilConnectionsSettings && window.basilConnectionsSettings.onEvent", args: event)
    }

    private func stateEvent(
        type: String,
        viewModel vm: ConnectionsSettingsViewModel,
        providerProfilesViewModel ppvm: ProviderProfilesViewModel
    ) -> [String: Any] {
        [
            "type": type,
            "starterServers": vm.starterServers.map { starterServerPayload($0) },
            "connections": vm.connections.map { connectionPayload($0) },
            "callLogEntries": vm.callLogEntries.map { callLogEntryPayload($0) },
            "isLoading": vm.isLoading,
            "isAddingConnection": vm.isAddingConnection,
            "isLoadingCallLog": vm.isLoadingCallLog,
            "errorMessage": vm.errorMessage as Any,
            "statusMessage": vm.statusMessage as Any,
            "pendingFlowFriendlyName": vm.pendingFlowFriendlyName as Any,
            "githubDeviceFlow": vm.githubDeviceFlow.map { deviceFlowPayload($0) } as Any,
            "isPollingGitHubDeviceFlow": vm.isPollingGitHubDeviceFlow,
            "providerProfiles": ppvm.profiles.map { providerProfileSummaryPayload($0) },
            "isLoadingProviderProfiles": ppvm.isLoading,
            "isMutatingProviderProfiles": ppvm.isMutating,
            "providerProfilesStatusMessage": ppvm.statusMessage as Any,
            "providerProfilesErrorMessage": ppvm.errorMessage as Any,
        ]
    }

    private func starterServerPayload(_ server: APIClient.MCPStarterServer) -> [String: Any] {
        [
            "id": server.id,
            "friendlyName": server.friendlyName,
            "serverUrl": server.serverUrl,
            "description": server.description,
        ]
    }

    private func deviceFlowPayload(_ flow: GitHubDeviceFlowState) -> [String: Any] {
        [
            "deviceCode": flow.deviceCode,
            "userCode": flow.userCode,
            "verificationUri": flow.verificationUri,
            "expiresIn": flow.expiresIn,
            "interval": flow.interval,
            "requestedScopes": flow.requestedScopes,
        ]
    }

    private func connectionPayload(_ connection: APIClient.MCPConnection) -> [String: Any] {
        [
            "id": connection.id,
            "friendlyName": connection.friendlyName,
            "description": connection.description as Any,
            "serverUrl": connection.serverUrl,
            "enabled": connection.enabled,
            "registeredAt": connection.registeredAt,
            "lastToolRefreshAt": connection.lastToolRefreshAt as Any,
            "lastConnectionCheckAt": connection.lastConnectionCheckAt as Any,
            "lastConnectionStatus": connection.lastConnectionStatus as Any,
            "lastConnectionStatusMessage": connection.lastConnectionStatusMessage as Any,
            "serverName": connection.serverName as Any,
            "serverInstructions": connection.serverInstructions as Any,
            "authKind": connection.authKind ?? "manual_token",
            "tools": connection.tools.map { tool -> [String: Any] in
                [
                    "name": tool.name,
                    "description": tool.description as Any,
                    "isReadOnlyHint": tool.isReadOnlyHint,
                    "policy": tool.policy,
                ]
            },
        ]
    }

    private func callLogEntryPayload(_ entry: APIClient.MCPCallLogEntry) -> [String: Any] {
        [
            "id": entry.id,
            "connectionId": entry.connectionId,
            "serverUrl": entry.serverUrl,
            "toolName": entry.toolName,
            "resultClassification": entry.resultClassification,
            "errorKind": entry.errorKind as Any,
            "errorMessage": entry.errorMessage as Any,
            "contentPreview": entry.contentPreview as Any,
            "startedAt": entry.startedAt,
            "completedAt": entry.completedAt as Any,
        ]
    }

    private func workspaceGrantPayload(_ grant: APIClient.ProviderProfileWorkspaceGrantSummary) -> [String: Any] {
        [
            "id": grant.id,
            "canonicalWorkspaceRoot": grant.canonicalWorkspaceRoot,
            "status": grant.status,
            "workspaceLabel": grant.workspaceLabel,
            "description": grant.description as Any,
            "routingHints": grant.routingHints,
            "revision": grant.revision,
        ]
    }

    private func providerProfileSummaryPayload(_ profile: APIClient.ProviderProfileSummary) -> [String: Any] {
        [
            "id": profile.id,
            "displayName": profile.displayName,
            "status": profile.status,
            "capabilityState": profile.capabilityState,
            "description": profile.description as Any,
            "routingHints": profile.routingHints,
            "revision": profile.revision,
            "hasObservedCapabilities": profile.hasObservedCapabilities,
            "activeWorkspaceGrants": profile.activeWorkspaceGrants.map { workspaceGrantPayload($0) },
            "isStructurallyValid": profile.isStructurallyValid,
            "validationError": profile.validationError as Any,
            "createdAt": profile.createdAt,
            "updatedAt": profile.updatedAt,
        ]
    }

    private func providerProfileConfigurationPayload(_ configuration: APIClient.ProviderProfileConfiguration) -> [String: Any] {
        [
            "id": configuration.id,
            "displayName": configuration.displayName,
            "status": configuration.status,
            "capabilityState": configuration.capabilityState,
            "description": configuration.description as Any,
            "routingHints": configuration.routingHints,
            "revision": configuration.revision,
            "hasObservedCapabilities": configuration.hasObservedCapabilities,
            "activeWorkspaceGrants": configuration.activeWorkspaceGrants.map { workspaceGrantPayload($0) },
            "isStructurallyValid": configuration.isStructurallyValid,
            "validationError": configuration.validationError as Any,
            "createdAt": configuration.createdAt,
            "updatedAt": configuration.updatedAt,
            "launchArgv": configuration.launchArgv,
            "environmentAllowlist": configuration.environmentAllowlist,
            "authenticationMethodId": configuration.authenticationMethodId as Any,
        ]
    }
}
