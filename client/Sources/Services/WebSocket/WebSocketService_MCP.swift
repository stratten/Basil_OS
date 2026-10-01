import Foundation

/// WebSocket bridge for remote MCP connector token storage.
///
/// The Python backend never persists OAuth tokens for remote MCP
/// servers. Instead it sends three message types over the live
/// `/ws` WebSocket connection, and the client (which owns Keychain)
/// services them:
///
///   * `mcp_token_store`   — backend just completed an OAuth flow;
///                            store these tokens in Keychain.
///   * `mcp_token_request` — backend is about to dispatch an MCP tool
///                            and needs the access token; respond with
///                            `mcp_token_response` carrying the token
///                            (or NSNull if it isn't present).
///   * `mcp_token_delete`  — user removed the connection; purge the
///                            corresponding Keychain entries.
///
/// All three messages use the `type` field (not `event`), matching
/// the existing Python -> Swift control-message convention used by
/// `auth_token_request` / `operation_state_query`.
final class WebSocketService_MCP {

    /// Persist a token pair pushed from the backend after a successful
    /// OAuth flow. ``connection_id`` namespaces the slot; the same id
    /// is later used by ``mcp_token_request`` to retrieve the token.
    @MainActor
    static func handleTokenStore(_ json: [String: Any]) {
        guard let connectionId = json["connection_id"] as? String,
              let accessToken = json["access_token"] as? String else {
            #if DEBUG
            DevLogger.shared.error(
                "🔌 mcp_token_store missing connection_id or access_token",
                context: "websocket"
            )
            #endif
            return
        }
        let refreshToken = json["refresh_token"] as? String
        do {
            // Every backend push is a complete grant: the Slack and generic OAuth
            // refresh paths resend the previous refresh token when the provider
            // omits a new one, so a missing refresh token here means the grant
            // has none and any stored one is stale.
            try AuthService.shared.storeMCPToken(
                connectionId: connectionId,
                accessToken: accessToken,
                refreshToken: refreshToken,
                replacingRefreshToken: true
            )
            #if DEBUG
            DevLogger.shared.info(
                "🔌 Stored MCP token for connection \(connectionId)",
                context: "websocket"
            )
            #endif
        } catch {
            DevLogger.shared.error(
                "🔌 Failed to store MCP token for \(connectionId): \(error)",
                context: "websocket"
            )
        }
    }

    /// Respond to a backend request for the access token associated
    /// with a given connection. The response carries the same
    /// ``correlation_id`` so the backend's awaiting future can be
    /// resolved deterministically.
    ///
    /// When the backend sets ``include_refresh_token: true`` (used by
    /// the Slack PKCE refresh path), the response also carries the
    /// refresh token from Keychain so Python can rotate the access
    /// token through Slack's token endpoint without forcing a full
    /// re-consent.
    @MainActor
    static func handleTokenRequest(_ json: [String: Any], parent: WebSocketService) {
        guard let connectionId = json["connection_id"] as? String,
              let correlationId = json["correlation_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error(
                "🔌 mcp_token_request missing connection_id or correlation_id",
                context: "websocket"
            )
            #endif
            return
        }

        let includeRefreshToken = (json["include_refresh_token"] as? Bool) ?? false

        // INFO (not #if DEBUG) so release logs can confirm the client actually
        // received the request — this is the top of the round-trip we need to
        // trace when the backend reports "Waiting for access".
        DevLogger.shared.info(
            "🔌 Received mcp_token_request for connection \(connectionId) correlation \(correlationId) (refresh requested: \(includeRefreshToken))",
            context: "websocket"
        )

        let tokenRequiresKeychainRead = !AuthService.shared.hasCachedMCPAccessToken(connectionId: connectionId)
        let refreshRequiresKeychainRead =
            includeRefreshToken && !AuthService.shared.hasCachedMCPRefreshToken(connectionId: connectionId)
        if tokenRequiresKeychainRead || refreshRequiresKeychainRead {
            sendTokenUserActionWaiting(
                parent: parent,
                connectionId: connectionId,
                correlationId: correlationId
            )
        }

        let token = AuthService.shared.getMCPToken(connectionId: connectionId)
        let refreshToken = includeRefreshToken
            ? AuthService.shared.getMCPRefreshToken(connectionId: connectionId)
            : nil

        var response: [String: Any] = [
            "type": "mcp_token_response",
            "correlation_id": correlationId,
            "connection_id": connectionId
        ]
        if let token = token {
            response["access_token"] = token
        } else {
            response["access_token"] = NSNull()
        }
        if includeRefreshToken {
            if let refreshToken = refreshToken {
                response["refresh_token"] = refreshToken
            } else {
                response["refresh_token"] = NSNull()
            }
        }

        guard let data = try? JSONSerialization.data(withJSONObject: response),
              let jsonString = String(data: data, encoding: .utf8) else {
            DevLogger.shared.error(
                "🔌 Failed to serialize mcp_token_response for \(connectionId)",
                context: "websocket"
            )
            return
        }
        parent.sendMessage(jsonString)

        // INFO (not #if DEBUG) so release logs can confirm the client sent the
        // response and with what correlation_id — the bottom of the round-trip.
        DevLogger.shared.info(
            "🔌 Sent mcp_token_response for connection \(connectionId) correlation \(correlationId) (access present: \(token != nil), refresh requested: \(includeRefreshToken), refresh present: \(refreshToken != nil))",
            context: "websocket"
        )
    }

    @MainActor
    private static func sendTokenUserActionWaiting(
        parent: WebSocketService,
        connectionId: String,
        correlationId: String
    ) {
        let payload: [String: Any] = [
            "type": "mcp_token_user_action_waiting",
            "correlation_id": correlationId,
            "connection_id": connectionId,
            "message": "Keychain access required"
        ]

        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let jsonString = String(data: data, encoding: .utf8) else {
            DevLogger.shared.error(
                "🔌 Failed to serialize mcp_token_user_action_waiting for \(connectionId)",
                context: "websocket"
            )
            return
        }

        parent.sendMessage(jsonString)
        DevLogger.shared.info(
            "🔌 Sent mcp_token_user_action_waiting for connection \(connectionId) correlation \(correlationId)",
            context: "websocket"
        )
    }

    /// Purge both token slots when the user removes a connection.
    @MainActor
    static func handleTokenDelete(_ json: [String: Any]) {
        guard let connectionId = json["connection_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error(
                "🔌 mcp_token_delete missing connection_id",
                context: "websocket"
            )
            #endif
            return
        }
        AuthService.shared.deleteMCPToken(connectionId: connectionId)
        #if DEBUG
        DevLogger.shared.info(
            "🔌 Deleted MCP tokens for connection \(connectionId)",
            context: "websocket"
        )
        #endif
    }
}
