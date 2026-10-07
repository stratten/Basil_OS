import AppKit
import Combine
import Foundation

extension SettingsShellWindowController {
    func wireConnectionsSettingsWebView(_ webView: ReactConnectionsSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadConnectionsSettingsAndSendInit() }
        }
        webView.onRequestStartOAuth = { [weak self] requestId, serverUrl, friendlyName, description in
            self?.performConnectionsStartOAuth(requestId: requestId, serverUrl: serverUrl, friendlyName: friendlyName, description: description)
        }
        webView.onRequestStartSlackOAuth = { [weak self] requestId, serverUrl, friendlyName, description in
            self?.performConnectionsStartSlackOAuth(requestId: requestId, serverUrl: serverUrl, friendlyName: friendlyName, description: description)
        }
        webView.onRequestStartGitHubDeviceFlow = { [weak self] requestId, serverUrl, friendlyName, description in
            self?.performConnectionsStartGitHubDeviceFlow(requestId: requestId, serverUrl: serverUrl, friendlyName: friendlyName, description: description)
        }
        webView.onRequestCancelGitHubDeviceFlow = { [weak self] requestId in
            self?.performConnectionsCancelGitHubDeviceFlow(requestId: requestId)
        }
        webView.onRequestOpenExternalUrl = { [weak self] requestId, url in
            self?.performConnectionsOpenExternalUrl(requestId: requestId, url: url)
        }
        webView.onRequestRegisterManualToken = { [weak self] requestId, serverUrl, friendlyName, description, bearerToken in
            self?.performConnectionsRegisterManualToken(requestId: requestId, serverUrl: serverUrl, friendlyName: friendlyName, description: description, bearerToken: bearerToken)
        }
        webView.onRequestDeleteConnection = { [weak self] requestId, connectionId in
            self?.performConnectionsDeleteConnection(requestId: requestId, connectionId: connectionId)
        }
        webView.onRequestRefreshTools = { [weak self] requestId, connectionId in
            self?.performConnectionsRefreshTools(requestId: requestId, connectionId: connectionId)
        }
        webView.onRequestUpdateConnectionMetadata = { [weak self] requestId, connectionId, friendlyName, description in
            self?.performConnectionsUpdateConnectionMetadata(requestId: requestId, connectionId: connectionId, friendlyName: friendlyName, description: description)
        }
        webView.onRequestCheckConnectionStatus = { [weak self] requestId, connectionId in
            self?.performConnectionsCheckConnectionStatus(requestId: requestId, connectionId: connectionId)
        }
        wireConnectionReconnectCallbacks(webView)
        webView.onRequestUpdatePolicy = { [weak self] requestId, connectionId, toolName, policy in
            self?.performConnectionsUpdatePolicy(requestId: requestId, connectionId: connectionId, toolName: toolName, policy: policy)
        }
        webView.onRequestRefreshCallLog = { [weak self] requestId in
            self?.performConnectionsRefreshCallLog(requestId: requestId)
        }
        webView.onRequestCreateProviderProfile = { [weak self] requestId, displayName, launchArgv, environmentAllowlist, authenticationMethodId, description, routingHints in
            self?.performConnectionsCreateProviderProfile(requestId: requestId, displayName: displayName, launchArgv: launchArgv, environmentAllowlist: environmentAllowlist, authenticationMethodId: authenticationMethodId, description: description, routingHints: routingHints)
        }
        webView.onRequestUpdateProviderProfile = { [weak self] requestId, profileId, expectedRevision, displayName, launchArgv, environmentAllowlist, authenticationMethodId, description, routingHints in
            self?.performConnectionsUpdateProviderProfile(requestId: requestId, profileId: profileId, expectedRevision: expectedRevision, displayName: displayName, launchArgv: launchArgv, environmentAllowlist: environmentAllowlist, authenticationMethodId: authenticationMethodId, description: description, routingHints: routingHints)
        }
        webView.onRequestSetProviderProfileEnabled = { [weak self] requestId, profileId, expectedRevision, enabled in
            self?.performConnectionsSetProviderProfileEnabled(requestId: requestId, profileId: profileId, expectedRevision: expectedRevision, enabled: enabled)
        }
        webView.onRequestRemoveProviderProfile = { [weak self] requestId, profileId, expectedRevision in
            self?.performConnectionsRemoveProviderProfile(requestId: requestId, profileId: profileId, expectedRevision: expectedRevision)
        }
        webView.onRequestLoadProviderProfileConfiguration = { [weak self] requestId, profileId in
            self?.performConnectionsLoadProviderProfileConfiguration(requestId: requestId, profileId: profileId)
        }
        webView.onRequestChooseWorkspaceFolder = { [weak self] requestId, profileId in
            self?.performConnectionsChooseWorkspaceFolder(requestId: requestId, profileId: profileId)
        }
        webView.onRequestCreateWorkspaceGrant = { [weak self] requestId, profileId, canonicalWorkspaceRoot, workspaceLabel, description, routingHints in
            self?.performConnectionsCreateWorkspaceGrant(requestId: requestId, profileId: profileId, canonicalWorkspaceRoot: canonicalWorkspaceRoot, workspaceLabel: workspaceLabel, description: description, routingHints: routingHints)
        }
        webView.onRequestUpdateWorkspaceGrant = { [weak self] requestId, profileId, grantId, expectedRevision, workspaceLabel, description, routingHints in
            self?.performConnectionsUpdateWorkspaceGrant(requestId: requestId, profileId: profileId, grantId: grantId, expectedRevision: expectedRevision, workspaceLabel: workspaceLabel, description: description, routingHints: routingHints)
        }
        webView.onRequestRevokeWorkspaceGrant = { [weak self] requestId, profileId, grantId, expectedRevision in
            self?.performConnectionsRevokeWorkspaceGrant(requestId: requestId, profileId: profileId, grantId: grantId, expectedRevision: expectedRevision)
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[CONNECTIONS_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }

        // See dossier settled decision 5: `ConnectionsSettingsViewModel`
        // already sets its own `@Published` properties from (a)
        // bridge-triggered awaits, (b) the `.mcpConnectionCompleted`
        // notification observer registered in its own `init()`, and (c)
        // the GitHub device-flow poll loop. This one debounced
        // subscription is sufficient to propagate all three completion
        // paths to React, matching Account's pattern exactly.
        connectionsObserverCancellable = connectionsViewModel.objectWillChange
            .debounce(for: .milliseconds(150), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.sendCombinedSnapshot()
            }

        // `ProviderProfilesViewModel` is a second, independent `@Published`
        // object (Settled Decision 2) -- its own debounced subscription
        // ensures a profile/grant mutation refreshes the combined snapshot
        // even though the two view models never touch each other directly.
        providerProfilesObserverCancellable = providerProfilesViewModel.objectWillChange
            .debounce(for: .milliseconds(150), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.sendCombinedSnapshot()
            }
    }

    private func sendCombinedSnapshot() {
        guard let webView = connectionsWebView else { return }
        webView.sendSnapshot(viewModel: connectionsViewModel, providerProfilesViewModel: providerProfilesViewModel)
    }

    private func loadConnectionsSettingsAndSendInit() async {
        connectionsLoadGeneration += 1
        let generation = connectionsLoadGeneration
        async let connectionsLoad: Void = connectionsViewModel.initialLoad()
        async let profilesLoad: Void = providerProfilesViewModel.loadProfiles()
        _ = await (connectionsLoad, profilesLoad)
        guard generation == connectionsLoadGeneration else { return }
        guard let webView = connectionsWebView else { return }
        webView.sendInit(viewModel: connectionsViewModel, providerProfilesViewModel: providerProfilesViewModel)
    }

    // MARK: - Native-side validation (mirrors PermissionsCommandSecurityPatch's validator precedent)

    static func validateExternalUrl(_ url: String) -> String? {
        guard let parsed = URL(string: url), parsed.scheme?.lowercased() == "https" else {
            return "Only https:// URLs can be opened."
        }
        return nil
    }

    static func isBlankOrWhitespace(_ value: String) -> Bool {
        value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private static func validateStartFlowFields(serverUrl: String, friendlyName: String) -> String? {
        if isBlankOrWhitespace(friendlyName) {
            return "A name is required."
        }
        if isBlankOrWhitespace(serverUrl) {
            return "A server URL is required."
        }
        return nil
    }

    static func validateProviderProfileFields(displayName: String, launchArgv: [String]) -> String? {
        if isBlankOrWhitespace(displayName) {
            return "A display name is required."
        }
        if launchArgv.isEmpty || isBlankOrWhitespace(launchArgv[0]) {
            return "An absolute executable path is required."
        }
        return nil
    }

    static func validateWorkspaceGrantFields(workspaceLabel: String) -> String? {
        if isBlankOrWhitespace(workspaceLabel) {
            return "A workspace label is required."
        }
        return nil
    }

    // MARK: - Actions

    private func performConnectionsStartOAuth(requestId: String, serverUrl: String, friendlyName: String, description: String?) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateStartFlowFields(serverUrl: serverUrl, friendlyName: friendlyName) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.startConnectionFlow(serverUrl: serverUrl, friendlyName: friendlyName, description: description)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsStartSlackOAuth(requestId: String, serverUrl: String, friendlyName: String, description: String?) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateStartFlowFields(serverUrl: serverUrl, friendlyName: friendlyName) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.startSlackConnectionFlow(serverUrl: serverUrl, friendlyName: friendlyName, description: description)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsStartGitHubDeviceFlow(requestId: String, serverUrl: String, friendlyName: String, description: String?) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateStartFlowFields(serverUrl: serverUrl, friendlyName: friendlyName) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.startGitHubDeviceFlow(serverUrl: serverUrl, friendlyName: friendlyName, description: description)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsCancelGitHubDeviceFlow(requestId: String) {
        guard let webView = connectionsWebView else { return }
        connectionsViewModel.cancelGitHubDeviceFlow()
        sendCombinedSnapshot()
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private func performConnectionsOpenExternalUrl(requestId: String, url: String) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateExternalUrl(url) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        guard let parsed = URL(string: url) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Invalid URL.")
            return
        }
        NSWorkspace.shared.open(parsed)
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private func performConnectionsRegisterManualToken(requestId: String, serverUrl: String, friendlyName: String, description: String?, bearerToken: String) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateStartFlowFields(serverUrl: serverUrl, friendlyName: friendlyName) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        if Self.isBlankOrWhitespace(bearerToken) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "A bearer token is required.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.registerManualTokenConnection(serverUrl: serverUrl, friendlyName: friendlyName, description: description, bearerToken: bearerToken)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsDeleteConnection(requestId: String, connectionId: String) {
        guard let webView = connectionsWebView else { return }
        guard let window else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "The Settings window is unavailable.")
            return
        }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Remove \(connection.friendlyName)?"
        alert.informativeText = "Basil will no longer be able to use this connection's tools. You can add it again later."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Remove")
        alert.addButton(withTitle: "Cancel")

        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn else {
                webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            Task { @MainActor in
                guard let self else { return }
                let vm = self.connectionsViewModel
                await vm.deleteConnection(connection)
                let actionSucceeded = vm.errorMessage == nil
                self.sendCombinedSnapshot()
                webView.sendIntentResult(
                    requestId: requestId,
                    status: actionSucceeded ? "success" : "error",
                    message: actionSucceeded ? nil : vm.errorMessage
                )
            }
        }
    }

    private func performConnectionsRefreshTools(requestId: String, connectionId: String) {
        guard let webView = connectionsWebView else { return }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.refreshTools(for: connection)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsUpdateConnectionMetadata(requestId: String, connectionId: String, friendlyName: String, description: String?) {
        guard let webView = connectionsWebView else { return }
        if Self.isBlankOrWhitespace(friendlyName) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "A name is required.")
            return
        }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.updateConnectionMetadata(for: connection, friendlyName: friendlyName, description: description)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsCheckConnectionStatus(requestId: String, connectionId: String) {
        guard let webView = connectionsWebView else { return }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.checkConnectionStatus(for: connection)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsUpdatePolicy(requestId: String, connectionId: String, toolName: String, policy: String) {
        guard let webView = connectionsWebView else { return }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.updatePolicy(for: connection, toolName: toolName, newPolicy: policy)
            let actionSucceeded = vm.errorMessage == nil
            sendCombinedSnapshot()
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? nil : vm.errorMessage
            )
        }
    }

    private func performConnectionsRefreshCallLog(requestId: String) {
        guard let webView = connectionsWebView else { return }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.loadCallLog()
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        }
    }

    // MARK: - Provider Profiles / Workspace Grants

    private func findProviderProfile(_ profileId: String, expectedRevision: Int, requestId: String, webView: ReactConnectionsSettingsWebView) -> APIClient.ProviderProfileSummary? {
        guard let profile = providerProfilesViewModel.profiles.first(where: { $0.id == profileId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That provider profile no longer exists.")
            return nil
        }
        guard profile.revision == expectedRevision else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "This provider profile was changed elsewhere. Reload and try again.")
            return nil
        }
        return profile
    }

    private func performConnectionsCreateProviderProfile(requestId: String, displayName: String, launchArgv: [String], environmentAllowlist: [String], authenticationMethodId: String?, description: String?, routingHints: [String]) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateProviderProfileFields(displayName: displayName, launchArgv: launchArgv) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        let configuration = APIClient.ProviderProfileConfigurationRequest(
            displayName: displayName,
            launchArgv: launchArgv,
            environmentAllowlist: environmentAllowlist,
            authenticationMethodId: authenticationMethodId,
            description: description,
            routingHints: routingHints
        )
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let didSave = await vm.createProfile(configuration: configuration)
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? vm.statusMessage : vm.errorMessage)
        }
    }

    private func performConnectionsUpdateProviderProfile(requestId: String, profileId: String, expectedRevision: Int, displayName: String, launchArgv: [String], environmentAllowlist: [String], authenticationMethodId: String?, description: String?, routingHints: [String]) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateProviderProfileFields(displayName: displayName, launchArgv: launchArgv) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        guard let profile = findProviderProfile(profileId, expectedRevision: expectedRevision, requestId: requestId, webView: webView) else { return }
        let configuration = APIClient.ProviderProfileConfigurationRequest(
            displayName: displayName,
            launchArgv: launchArgv,
            environmentAllowlist: environmentAllowlist,
            authenticationMethodId: authenticationMethodId,
            description: description,
            routingHints: routingHints
        )
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let didSave = await vm.updateProfile(profile: profile, configuration: configuration)
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? vm.statusMessage : vm.errorMessage)
        }
    }

    private func performConnectionsSetProviderProfileEnabled(requestId: String, profileId: String, expectedRevision: Int, enabled: Bool) {
        guard let webView = connectionsWebView else { return }
        guard let profile = findProviderProfile(profileId, expectedRevision: expectedRevision, requestId: requestId, webView: webView) else { return }
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let didSave = await vm.setProfileEnabled(profile, enabled: enabled)
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? vm.statusMessage : vm.errorMessage)
        }
    }

    private func performConnectionsRemoveProviderProfile(requestId: String, profileId: String, expectedRevision: Int) {
        guard let webView = connectionsWebView else { return }
        guard let window else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "The Settings window is unavailable.")
            return
        }
        guard let profile = findProviderProfile(profileId, expectedRevision: expectedRevision, requestId: requestId, webView: webView) else { return }
        let alert = NSAlert()
        alert.messageText = "Remove \(profile.displayName)?"
        alert.informativeText = "This removes the profile from future provider catalog eligibility. Historical provider runs are preserved, no provider process is stopped, and no local files are deleted."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Remove")
        alert.addButton(withTitle: "Cancel")

        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn else {
                webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            Task { @MainActor in
                guard let self else { return }
                let vm = self.providerProfilesViewModel
                let didSave = await vm.removeProfile(profile)
                self.sendCombinedSnapshot()
                webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? nil : vm.errorMessage)
            }
        }
    }

    private func performConnectionsLoadProviderProfileConfiguration(requestId: String, profileId: String) {
        guard let webView = connectionsWebView else { return }
        guard let profile = providerProfilesViewModel.profiles.first(where: { $0.id == profileId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That provider profile no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let configuration = await vm.loadProfileConfiguration(for: profile)
            webView.sendProviderProfileConfiguration(requestId: requestId, configuration: configuration, errorMessage: configuration == nil ? vm.errorMessage : nil)
            webView.sendIntentResult(requestId: requestId, status: configuration != nil ? "success" : "error", message: configuration != nil ? nil : vm.errorMessage)
        }
    }

    private func performConnectionsChooseWorkspaceFolder(requestId: String, profileId: String) {
        guard let webView = connectionsWebView else { return }
        let panel = NSOpenPanel()
        panel.applyBasilThemedAppearance()
        panel.allowsMultipleSelection = false
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = false
        panel.title = "Choose Workspace Folder"
        panel.begin { [weak self] response in
            guard let self else { return }
            guard response == .OK, let url = panel.urls.first else {
                webView.sendWorkspaceFolderChosen(requestId: requestId, profileId: profileId, canonicalWorkspaceRoot: nil, errorMessage: nil)
                webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            switch WorkspaceDirectoryCanonicalizer.canonicalize(url) {
            case .success(let root):
                webView.sendWorkspaceFolderChosen(requestId: requestId, profileId: profileId, canonicalWorkspaceRoot: root, errorMessage: nil)
                webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            case .failure(let failure):
                self.providerProfilesViewModel.errorMessage = failure.userMessage
                self.sendCombinedSnapshot()
                webView.sendWorkspaceFolderChosen(requestId: requestId, profileId: profileId, canonicalWorkspaceRoot: nil, errorMessage: failure.userMessage)
                webView.sendIntentResult(requestId: requestId, status: "error", message: failure.userMessage)
            }
        }
    }

    private func performConnectionsCreateWorkspaceGrant(requestId: String, profileId: String, canonicalWorkspaceRoot: String, workspaceLabel: String, description: String?, routingHints: [String]) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateWorkspaceGrantFields(workspaceLabel: workspaceLabel) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        guard let profile = providerProfilesViewModel.profiles.first(where: { $0.id == profileId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That provider profile no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let didSave = await vm.createWorkspaceGrant(for: profile, canonicalWorkspaceRoot: canonicalWorkspaceRoot, workspaceLabel: workspaceLabel, description: description, routingHints: routingHints)
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? vm.statusMessage : vm.errorMessage)
        }
    }

    private func performConnectionsUpdateWorkspaceGrant(requestId: String, profileId: String, grantId: String, expectedRevision: Int, workspaceLabel: String, description: String?, routingHints: [String]) {
        guard let webView = connectionsWebView else { return }
        if let validationError = Self.validateWorkspaceGrantFields(workspaceLabel: workspaceLabel) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: validationError)
            return
        }
        guard let profile = providerProfilesViewModel.profiles.first(where: { $0.id == profileId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That provider profile no longer exists.")
            return
        }
        guard let grant = profile.activeWorkspaceGrants.first(where: { $0.id == grantId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That workspace authorization no longer exists.")
            return
        }
        guard grant.revision == expectedRevision else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "This workspace authorization was changed elsewhere. Reload and try again.")
            return
        }
        Task { @MainActor in
            let vm = providerProfilesViewModel
            let didSave = await vm.updateWorkspaceGrant(profile: profile, grant: grant, workspaceLabel: workspaceLabel, description: description, routingHints: routingHints)
            sendCombinedSnapshot()
            webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? vm.statusMessage : vm.errorMessage)
        }
    }

    private func performConnectionsRevokeWorkspaceGrant(requestId: String, profileId: String, grantId: String, expectedRevision: Int) {
        guard let webView = connectionsWebView else { return }
        guard let window else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "The Settings window is unavailable.")
            return
        }
        guard let profile = providerProfilesViewModel.profiles.first(where: { $0.id == profileId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That provider profile no longer exists.")
            return
        }
        guard let grant = profile.activeWorkspaceGrants.first(where: { $0.id == grantId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That workspace authorization no longer exists.")
            return
        }
        guard grant.revision == expectedRevision else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "This workspace authorization was changed elsewhere. Reload and try again.")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Revoke \(grant.workspaceLabel)?"
        alert.informativeText = "This revokes future workspace authorization, preserves history, and does not delete local files."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Revoke")
        alert.addButton(withTitle: "Cancel")

        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn else {
                webView.sendIntentResult(requestId: requestId, status: "canceled", message: nil)
                return
            }
            Task { @MainActor in
                guard let self else { return }
                let vm = self.providerProfilesViewModel
                let didSave = await vm.revokeWorkspaceGrant(profile: profile, grant: grant)
                self.sendCombinedSnapshot()
                webView.sendIntentResult(requestId: requestId, status: didSave ? "success" : "error", message: didSave ? nil : vm.errorMessage)
            }
        }
    }
}
