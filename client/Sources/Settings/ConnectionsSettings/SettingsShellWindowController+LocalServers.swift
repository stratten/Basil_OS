import Foundation

extension SettingsShellWindowController {
    func wireLocalServerCallbacks(_ webView: ReactConnectionsSettingsWebView) {
        webView.onLocalServerIntent = { [weak self] intent in
            self?.handleLocalServerIntent(intent)
        }
    }

    static func validateLocalServerRegistration(_ registration: APIClient.LocalServerRegistration, secretValues: [String: String]) -> String? {
        if isBlankOrWhitespace(registration.friendlyName) {
            return "A name is required."
        }
        if isBlankOrWhitespace(registration.command) {
            return "A command is required."
        }
        if let companion = registration.companion, isBlankOrWhitespace(companion.command) {
            return "The background program needs a command."
        }
        for name in LocalServerSecretKey.declaredNames(in: registration) where isBlankOrWhitespace(secretValues[name] ?? "") {
            return "A value for \(name) is required."
        }
        return nil
    }

    private func handleLocalServerIntent(_ intent: LocalServerIntent) {
        switch intent {
        case .register(let requestId, let registration, let secretValues):
            if let validationError = Self.validateLocalServerRegistration(registration, secretValues: secretValues) {
                connectionsWebView?.sendIntentResult(requestId: requestId, status: "error", message: validationError)
                return
            }
            runLocalServerAction(requestId: requestId) { viewModel in
                await viewModel.registerLocalServer(registration, secretValues: secretValues)
            }
        case .startCompanion(let requestId, let connectionId):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.startLocalServerCompanion(for: connection)
            }
        case .stopCompanion(let requestId, let connectionId):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.stopLocalServerCompanion(for: connection)
            }
        case .setStartWithBasil(let requestId, let connectionId, let enabled):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.setLocalServerCompanionStartWithBasil(for: connection, enabled: enabled)
            }
        case .saveSecrets(let requestId, let connectionId, let secretValues):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.saveLocalServerSecrets(for: connection, secretValues: secretValues)
            }
        case .refreshStatus(let requestId, let connectionId):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.refreshLocalServerStatus(for: connection)
            }
        case .prepare(let requestId, let connectionId):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.prepareLocalServer(for: connection)
            }
        case .cancelPrepare(let requestId, let connectionId):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.cancelPrepareLocalServer(for: connection)
            }
        case .installRequirement(let requestId, let connectionId, let name, let command):
            runLocalServerAction(requestId: requestId, connectionId: connectionId) { viewModel, connection in
                await viewModel.installLocalServerRequirement(for: connection, name: name, command: command)
            }
        }
    }

    private func runLocalServerAction(
        requestId: String,
        connectionId: String,
        _ action: @escaping @MainActor (ConnectionsSettingsViewModel, APIClient.MCPConnection) async -> Void
    ) {
        guard let webView = connectionsWebView else { return }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        runLocalServerAction(requestId: requestId) { viewModel in
            await action(viewModel, connection)
        }
    }

    private func runLocalServerAction(
        requestId: String,
        _ action: @escaping @MainActor (ConnectionsSettingsViewModel) async -> Void
    ) {
        guard let webView = connectionsWebView else { return }
        Task { @MainActor in
            let viewModel = connectionsViewModel
            await action(viewModel)
            let actionSucceeded = viewModel.errorMessage == nil
            webView.sendSnapshot(viewModel: viewModel, providerProfilesViewModel: providerProfilesViewModel)
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? viewModel.statusMessage : viewModel.errorMessage
            )
        }
    }
}
