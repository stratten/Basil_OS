import Foundation

/// Registers a bearer-token connection, saves the token in the Keychain vault, and proves the service accepts it by fetching its tool list.
///
/// This is the same sequence the Connections settings screen runs for "Manual Bearer Token Server", with two additions for connections the agent asked for: a failed check removes the half-made connection and its token so nothing unusable is left behind, and every failure message is scrubbed of the token before it is shown or sent anywhere.
@MainActor
struct ConnectionTokenConnector {
    @MainActor
    struct Operations {
        var register: @MainActor (_ serverUrl: String, _ friendlyName: String, _ description: String?) async throws -> APIClient.MCPConnection
        var storeToken: @MainActor (_ connectionId: String, _ token: String) throws -> Void
        var verify: @MainActor (_ connectionId: String) async throws -> APIClient.MCPConnection
        var removeConnection: @MainActor (_ connectionId: String) async throws -> Void
        var deleteToken: @MainActor (_ connectionId: String) -> Void

        static var live: Operations {
            Operations(
                register: { serverUrl, friendlyName, description in
                    try await APIClient.shared.registerManualTokenMCPConnection(
                        serverUrl: serverUrl,
                        friendlyName: friendlyName,
                        description: description
                    )
                },
                storeToken: { connectionId, token in
                    try MCPTokenStore.shared.store(connectionId: connectionId, accessToken: token)
                },
                verify: { connectionId in
                    try await APIClient.shared.refreshMCPTools(connectionId: connectionId)
                },
                removeConnection: { connectionId in
                    try await APIClient.shared.deleteMCPConnection(connectionId: connectionId)
                },
                deleteToken: { connectionId in
                    MCPTokenStore.shared.delete(connectionId: connectionId)
                }
            )
        }
    }

    enum Outcome: Equatable {
        case connected(connectionId: String, toolCount: Int, friendlyName: String, description: String?)
        case failed(message: String)
    }

    var operations: Operations = .live

    /// Pasted tokens often carry the "Bearer " prefix from an example header; the stored value must not.
    static func cleanedToken(_ raw: String) -> String {
        var token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if token.lowercased() == "bearer" {
            return ""
        }
        if token.lowercased().hasPrefix("bearer"), let separator = token.dropFirst("bearer".count).first, separator.isWhitespace {
            token = String(token.dropFirst("bearer".count)).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return token
    }

    /// Replaces every occurrence of the token (and its longer leading fragments, which some services echo back) with a placeholder.
    static func scrubbed(_ message: String, token: String) -> String {
        guard !token.isEmpty else { return message }
        var result = message.replacingOccurrences(of: token, with: "[token]")
        for length in [24, 16, 12, 8] where token.count > length {
            result = result.replacingOccurrences(of: String(token.prefix(length)), with: "[token]")
        }
        return result
    }

    func connect(serverUrl: String, friendlyName: String, description: String?, token rawToken: String) async -> Outcome {
        let token = Self.cleanedToken(rawToken)
        guard !token.isEmpty else {
            return .failed(message: "Enter the token first.")
        }
        let connection: APIClient.MCPConnection
        do {
            connection = try await operations.register(serverUrl, friendlyName, description)
        } catch {
            return .failed(message: "Could not add \(friendlyName): \(Self.scrubbed(error.localizedDescription, token: token))")
        }
        do {
            try operations.storeToken(connection.id, token)
        } catch {
            await discard(connection.id)
            return .failed(message: "Could not save the token to your Keychain: \(Self.scrubbed(error.localizedDescription, token: token))")
        }
        do {
            let verified = try await operations.verify(connection.id)
            return .connected(connectionId: verified.id, toolCount: verified.tools.count, friendlyName: friendlyName, description: description)
        } catch {
            await discard(connection.id)
            return .failed(message: "\(friendlyName) did not accept the token: \(Self.scrubbed(error.localizedDescription, token: token))")
        }
    }

    private func discard(_ connectionId: String) async {
        try? await operations.removeConnection(connectionId)
        operations.deleteToken(connectionId)
    }
}
