import Foundation

extension ConnectionsSettingsViewModel {

    /// Saves each declared secret in the Keychain under the new connection's id, then asks the backend to add the program. The values never travel to the backend; it asks for them by account when it launches the program.
    func registerLocalServer(_ registration: APIClient.LocalServerRegistration, secretValues: [String: String]) async {
        isAddingConnection = true
        errorMessage = nil
        statusMessage = nil
        defer { isAddingConnection = false }

        var request = registration
        let connectionId = UUID().uuidString.lowercased()
        request.connectionId = connectionId
        var storedAccounts: [String] = []
        do {
            for name in LocalServerSecretKey.declaredNames(in: registration) {
                guard let value = secretValues[name], !value.isEmpty else {
                    throw LocalServerSecretError.missingValue(name)
                }
                let account = LocalServerSecretKey.account(connectionId: connectionId, name: name)
                try MCPTokenStore.shared.store(connectionId: account, accessToken: value)
                storedAccounts.append(account)
            }
            let connection = try await APIClient.shared.registerLocalServer(request)
            replaceConnection(connection)
            if let install = connection.localServer?.install, !install.ready {
                statusMessage = "Added \(connection.friendlyName). It needs setup first: review what it will install and download, then choose Prepare."
            } else {
                statusMessage = "Added \(connection.friendlyName) with \(connection.tools.count) tools."
            }
        } catch {
            for account in storedAccounts {
                MCPTokenStore.shared.delete(connectionId: account)
            }
            errorMessage = "Could not add \(registration.friendlyName): \(error.localizedDescription)"
        }
    }

    /// Saves values for secrets an existing program is missing (for example one the agent added), then starts its background program and refreshes its tools.
    func saveLocalServerSecrets(for connection: APIClient.MCPConnection, secretValues: [String: String]) async {
        errorMessage = nil
        statusMessage = nil
        guard let details = connection.localServer else {
            errorMessage = "\(connection.friendlyName) is not a program on this Mac."
            return
        }
        let supplied = LocalServerSecretKey.declaredNames(in: details).filter { !(secretValues[$0] ?? "").isEmpty }
        guard !supplied.isEmpty else {
            errorMessage = "Enter a value for at least one secret."
            return
        }
        do {
            for name in supplied {
                let account = LocalServerSecretKey.account(connectionId: connection.id, name: name)
                try MCPTokenStore.shared.store(connectionId: account, accessToken: secretValues[name] ?? "")
            }
        } catch {
            errorMessage = "Could not save the secret values for \(connection.friendlyName): \(error.localizedDescription)"
            return
        }
        if details.companion != nil {
            do {
                let updated = try await APIClient.shared.startLocalServerCompanion(connectionId: connection.id)
                replaceConnection(updated)
                if let failure = LocalServerCompanionMessages.failure(in: updated) {
                    errorMessage = "Saved the values, but the background program did not start. \(failure)"
                    return
                }
            } catch {
                errorMessage = "Saved the values, but the background program for \(connection.friendlyName) could not be started: \(error.localizedDescription)"
                return
            }
        }
        await refreshTools(for: connection)
    }

    func startLocalServerCompanion(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.startLocalServerCompanion(connectionId: connection.id)
            replaceConnection(updated)
            if let failure = LocalServerCompanionMessages.failure(in: updated) {
                errorMessage = failure
            } else {
                statusMessage = "Started the background program for \(updated.friendlyName)."
            }
        } catch {
            errorMessage = "Could not start the background program for \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func stopLocalServerCompanion(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.stopLocalServerCompanion(connectionId: connection.id)
            replaceConnection(updated)
            statusMessage = "Stopped the background program for \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not stop the background program for \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func setLocalServerCompanionStartWithBasil(for connection: APIClient.MCPConnection, enabled: Bool) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.setLocalServerCompanionStartWithBasil(connectionId: connection.id, startWithBasil: enabled)
            replaceConnection(updated)
            statusMessage = enabled
                ? "The background program for \(updated.friendlyName) will start whenever Basil starts."
                : "The background program for \(updated.friendlyName) will start the first time it is used."
        } catch {
            errorMessage = "Could not change the setting for \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    /// Fetches the server's current setup and background-program state. Silent: it neither shows a message nor clears one, because the page asks every few seconds while something is changing.
    func refreshLocalServerStatus(for connection: APIClient.MCPConnection) async {
        guard let updated = try? await APIClient.shared.localServerStatus(connectionId: connection.id) else { return }
        replaceConnection(updated)
    }

    /// Starts getting what the server's recipe lists. It returns at once; the page watches the progress.
    func prepareLocalServer(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.prepareLocalServer(connectionId: connection.id)
            replaceConnection(updated)
            statusMessage = "Preparing \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not prepare \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func cancelPrepareLocalServer(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.cancelPrepareLocalServer(connectionId: connection.id)
            replaceConnection(updated)
            statusMessage = "Stopped preparing \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not stop preparing \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    /// Installs one program the recipe needs. Choosing the button is the approval, and `command` is the exact text it showed.
    func installLocalServerRequirement(for connection: APIClient.MCPConnection, name: String, command: String) async {
        errorMessage = nil
        statusMessage = nil
        do {
            let updated = try await APIClient.shared.installLocalServerRequirement(connectionId: connection.id, name: name, command: command)
            replaceConnection(updated)
            statusMessage = "Installing \(name) for \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not install \(name): \(error.localizedDescription)"
        }
    }
}
