import Foundation

extension SettingsShellWindowController {
    func wireConnectionReconnectCallbacks(_ webView: ReactConnectionsSettingsWebView) {
        webView.onRequestReconnectConnection = { [weak self] requestId, connectionId in
            self?.performConnectionsReconnect(requestId: requestId, connectionId: connectionId)
        }
        webView.onRequestReplaceConnectionToken = { [weak self] requestId, connectionId, bearerToken in
            self?.performConnectionsReplaceToken(requestId: requestId, connectionId: connectionId, bearerToken: bearerToken)
        }
    }

    private func performConnectionsReconnect(requestId: String, connectionId: String) {
        guard let webView = connectionsWebView else { return }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.reconnect(connection)
            let actionSucceeded = vm.errorMessage == nil
            webView.sendSnapshot(viewModel: vm, providerProfilesViewModel: providerProfilesViewModel)
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }

    private func performConnectionsReplaceToken(requestId: String, connectionId: String, bearerToken: String) {
        guard let webView = connectionsWebView else { return }
        if Self.isBlankOrWhitespace(bearerToken) {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "A bearer token is required.")
            return
        }
        guard let connection = connectionsViewModel.connections.first(where: { $0.id == connectionId }) else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "That connection no longer exists.")
            return
        }
        guard (connection.authKind ?? "manual_token") == "manual_token" else {
            webView.sendIntentResult(requestId: requestId, status: "error", message: "\(connection.friendlyName) signs in through its provider. Use Reconnect instead.")
            return
        }
        Task { @MainActor in
            let vm = connectionsViewModel
            await vm.replaceManualToken(for: connection, bearerToken: bearerToken)
            let actionSucceeded = vm.errorMessage == nil
            webView.sendSnapshot(viewModel: vm, providerProfilesViewModel: providerProfilesViewModel)
            webView.sendIntentResult(
                requestId: requestId,
                status: actionSucceeded ? "success" : "error",
                message: actionSucceeded ? vm.statusMessage : vm.errorMessage
            )
        }
    }
}
