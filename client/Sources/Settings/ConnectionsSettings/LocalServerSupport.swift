import Foundation

/// The Keychain account for one secret of one local server. The backend asks for the same account through `mcp_token_request`, so this format must match `secret_account` in `local_server_secrets.py`.
enum LocalServerSecretKey {
    static let infix = ".env."

    static func account(connectionId: String, name: String) -> String {
        "\(connectionId)\(infix)\(name)"
    }

    /// Every secret name a registration declares, the server's first, each name once.
    static func declaredNames(in registration: APIClient.LocalServerRegistration) -> [String] {
        unique(registration.secretEnv + (registration.companion?.secretEnv ?? []))
    }

    /// Every secret name an existing local server declares, the server's first, each name once.
    static func declaredNames(in details: APIClient.LocalServerDetails) -> [String] {
        unique(details.secretEnv + (details.companion?.secretEnv ?? []))
    }

    private static func unique(_ names: [String]) -> [String] {
        var seen = Set<String>()
        return names.filter { seen.insert($0).inserted }
    }
}

enum LocalServerSecretError: LocalizedError {
    case missingValue(String)

    var errorDescription: String? {
        switch self {
        case .missingValue(let name):
            return "A value for \(name) is required."
        }
    }
}

enum LocalServerCompanionMessages {
    /// The sentence to show when the background program is not usable, or nil when it is starting or running (or the connection has none).
    static func failure(in connection: APIClient.MCPConnection) -> String? {
        guard let companion = connection.localServer?.companion else { return nil }
        switch companion.status {
        case "failed":
            let reason = companion.lastError?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return reason.isEmpty ? "The background program for \(connection.friendlyName) stopped unexpectedly." : reason
        case "needs_secrets":
            return "The background program for \(connection.friendlyName) is missing a secret value."
        default:
            return nil
        }
    }
}
