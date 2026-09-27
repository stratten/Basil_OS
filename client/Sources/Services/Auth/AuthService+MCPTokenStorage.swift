import Foundation

// MARK: - MCP Connector Token Storage
//
// Remote MCP server access tokens live in Keychain on the client, namespaced per
// connection so each user-registered MCP server (Linear, GitHub, custom) has
// its own slot. The Python backend never persists these tokens to disk; it asks
// the client for them over the WebSocket bridge each time a tool call is
// dispatched.
@MainActor
extension AuthService {
    private func mcpAccessTokenKey(connectionId: String) -> String {
        BasilRuntimeProfile.credentialKey("com.basil.mcpToken.\(connectionId)")
    }

    private func mcpRefreshTokenKey(connectionId: String) -> String {
        BasilRuntimeProfile.credentialKey("com.basil.mcpRefreshToken.\(connectionId)")
    }

    /// Persist the access token for a remote MCP connection. If a refresh token
    /// is supplied it is stored alongside; passing nil leaves any existing
    /// refresh token in place.
    func storeMCPToken(connectionId: String, accessToken: String, refreshToken: String? = nil) throws {
        try saveToKeychain(key: mcpAccessTokenKey(connectionId: connectionId), value: accessToken)
        cachedMCPAccessTokens[connectionId] = accessToken
        if let refresh = refreshToken {
            try saveToKeychain(key: mcpRefreshTokenKey(connectionId: connectionId), value: refresh)
            cachedMCPRefreshTokens[connectionId] = refresh
        }
    }

    /// Read the access token for a remote MCP connection. Cache hits avoid
    /// touching Keychain, so they cannot present a macOS password prompt.
    func getMCPToken(connectionId: String) -> String? {
        if let cached = cachedMCPAccessTokens[connectionId] {
            return cached
        }
        guard let value = getFromKeychain(key: mcpAccessTokenKey(connectionId: connectionId)) else {
            return nil
        }
        cachedMCPAccessTokens[connectionId] = value
        return value
    }

    /// Return whether the next MCP access-token request can be served from
    /// memory without touching Keychain.
    func hasCachedMCPAccessToken(connectionId: String) -> Bool {
        cachedMCPAccessTokens[connectionId] != nil
    }

    /// Read the refresh token, if any, for a remote MCP connection. Used when
    /// an OAuth coordinator refreshes instead of triggering full re-consent.
    func getMCPRefreshToken(connectionId: String) -> String? {
        if let cached = cachedMCPRefreshTokens[connectionId] {
            return cached
        }
        guard let value = getFromKeychain(key: mcpRefreshTokenKey(connectionId: connectionId)) else {
            return nil
        }
        cachedMCPRefreshTokens[connectionId] = value
        return value
    }

    /// Return whether the next MCP refresh-token request can be served from
    /// memory without touching Keychain.
    func hasCachedMCPRefreshToken(connectionId: String) -> Bool {
        cachedMCPRefreshTokens[connectionId] != nil
    }

    /// Remove both token slots for a remote MCP connection. Called when the
    /// user deletes the connection from Settings.
    func deleteMCPToken(connectionId: String) {
        cachedMCPAccessTokens.removeValue(forKey: connectionId)
        cachedMCPRefreshTokens.removeValue(forKey: connectionId)
        deleteFromKeychain(key: mcpAccessTokenKey(connectionId: connectionId))
        deleteFromKeychain(key: mcpRefreshTokenKey(connectionId: connectionId))
    }
}
