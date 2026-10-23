import Foundation

// MARK: - Connections (Remote MCP Servers) API
//
// Wrapper over `/settings/connections/*` for the Connections settings
// tab. All shapes mirror the Pydantic models in
// `backend/src/api/routes/connections_routes.py` (StarterServer,
// ConnectionDTO, CallLogEntry, etc.). When the OpenAPI generator is
// re-run these will be replaced by generated_models equivalents; the
// hand-rolled shapes here keep the UI shippable until then.

extension APIClient {

    struct MCPStarterServer: Codable, Identifiable, Hashable {
        let id: String
        let friendlyName: String
        let serverUrl: String
        let description: String

        enum CodingKeys: String, CodingKey {
            case id
            case friendlyName = "friendly_name"
            case serverUrl = "server_url"
            case description
        }
    }

    struct MCPConnectionTool: Codable, Identifiable, Hashable {
        let name: String
        let description: String?
        let isReadOnlyHint: Bool
        let policy: String

        var id: String { name }

        enum CodingKeys: String, CodingKey {
            case name
            case description
            case isReadOnlyHint = "is_read_only_hint"
            case policy
        }
    }

    struct MCPConnection: Codable, Identifiable, Hashable {
        let id: String
        let friendlyName: String
        let description: String?
        let serverUrl: String
        let enabled: Bool
        let registeredAt: String
        let lastToolRefreshAt: String?
        let lastConnectionCheckAt: String?
        let lastConnectionStatus: String?
        let lastConnectionStatusMessage: String?
        let serverName: String?
        let serverInstructions: String?
        let authKind: String?
        let tools: [MCPConnectionTool]

        enum CodingKeys: String, CodingKey {
            case id
            case friendlyName = "friendly_name"
            case description
            case serverUrl = "server_url"
            case enabled
            case registeredAt = "registered_at"
            case lastToolRefreshAt = "last_tool_refresh_at"
            case lastConnectionCheckAt = "last_connection_check_at"
            case lastConnectionStatus = "last_connection_status"
            case lastConnectionStatusMessage = "last_connection_status_message"
            case serverName = "server_name"
            case serverInstructions = "server_instructions"
            case authKind = "auth_kind"
            case tools
        }
    }

    struct MCPCallLogEntry: Codable, Identifiable, Hashable {
        let id: String
        let connectionId: String
        let serverUrl: String
        let toolName: String
        let resultClassification: String
        let errorKind: String?
        let errorMessage: String?
        let contentPreview: String?
        let startedAt: String
        let completedAt: String?

        enum CodingKeys: String, CodingKey {
            case id
            case connectionId = "connection_id"
            case serverUrl = "server_url"
            case toolName = "tool_name"
            case resultClassification = "result_classification"
            case errorKind = "error_kind"
            case errorMessage = "error_message"
            case contentPreview = "content_preview"
            case startedAt = "started_at"
            case completedAt = "completed_at"
        }
    }

    struct MCPToolPolicyUpdate: Codable {
        let toolName: String
        let policy: String

        enum CodingKeys: String, CodingKey {
            case toolName = "tool_name"
            case policy
        }
    }

    private struct ConnectionsListResponse: Codable {
        let connections: [MCPConnection]
    }

    private struct StarterServersResponse: Codable {
        let starterServers: [MCPStarterServer]
        enum CodingKeys: String, CodingKey {
            case starterServers = "starter_servers"
        }
    }

    private struct StartOAuthRequest: Codable {
        let serverUrl: String
        let friendlyName: String
        let description: String?
        let connectionId: String?
        enum CodingKeys: String, CodingKey {
            case serverUrl = "server_url"
            case friendlyName = "friendly_name"
            case description
            case connectionId = "connection_id"
        }
    }

    private struct StartOAuthResponse: Codable {
        let state: String
        let authorizationUrl: String
        enum CodingKeys: String, CodingKey {
            case state
            case authorizationUrl = "authorization_url"
        }
    }

    private struct RegisterManualTokenConnectionRequest: Codable {
        let serverUrl: String
        let friendlyName: String
        let description: String?
        enum CodingKeys: String, CodingKey {
            case serverUrl = "server_url"
            case friendlyName = "friendly_name"
            case description
        }
    }

    struct GitHubDeviceFlowStartResponse: Codable, Hashable {
        let deviceCode: String
        let userCode: String
        let verificationUri: String
        let expiresIn: Int
        let interval: Int
        let requestedScopes: [String]

        enum CodingKeys: String, CodingKey {
            case deviceCode = "device_code"
            case userCode = "user_code"
            case verificationUri = "verification_uri"
            case expiresIn = "expires_in"
            case interval
            case requestedScopes = "requested_scopes"
        }
    }

    struct GitHubDeviceFlowPollResponse: Codable, Hashable {
        let status: String
        let interval: Int?
        let connection: MCPConnection?
        let message: String?
    }

    private struct GitHubDeviceFlowStartRequest: Codable {
        let friendlyName: String
        let serverUrl: String
        let description: String?
        let connectionId: String?
        enum CodingKeys: String, CodingKey {
            case friendlyName = "friendly_name"
            case serverUrl = "server_url"
            case description
            case connectionId = "connection_id"
        }
    }

    private struct GitHubDeviceFlowPollRequest: Codable {
        let deviceCode: String
        enum CodingKeys: String, CodingKey {
            case deviceCode = "device_code"
        }
    }

    // MARK: Slack PKCE

    struct SlackOAuthStartResponse: Codable, Hashable {
        let state: String
        let authorizationUrl: String
        let requestedScopes: [String]
        enum CodingKeys: String, CodingKey {
            case state
            case authorizationUrl = "authorization_url"
            case requestedScopes = "requested_scopes"
        }
    }

    private struct SlackOAuthStartRequest: Codable {
        let friendlyName: String
        let serverUrl: String
        let description: String?
        let requestedScopes: [String]?
        let connectionId: String?
        enum CodingKeys: String, CodingKey {
            case friendlyName = "friendly_name"
            case serverUrl = "server_url"
            case description
            case requestedScopes = "requested_scopes"
            case connectionId = "connection_id"
        }
    }

    private struct SlackOAuthCompleteRequest: Codable {
        let state: String
        let code: String
    }

    struct SlackOAuthCompleteResponse: Codable, Hashable {
        let status: String
        let connection: MCPConnection?
        let message: String?
    }

    private struct ToolPolicyBulkUpdate: Codable {
        let policies: [MCPToolPolicyUpdate]
    }

    private struct ConnectionMetadataUpdateRequest: Codable {
        let friendlyName: String
        let description: String?
        enum CodingKeys: String, CodingKey {
            case friendlyName = "friendly_name"
            case description
        }
    }

    struct ConnectionStatusResponse: Codable, Hashable {
        let connection: MCPConnection
        let status: String
        let message: String
        let checkedAt: String
        let refreshedCredentials: Bool
        let userActionRequired: String?

        enum CodingKeys: String, CodingKey {
            case connection
            case status
            case message
            case checkedAt = "checked_at"
            case refreshedCredentials = "refreshed_credentials"
            case userActionRequired = "user_action_required"
        }
    }

    private struct CallLogResponse: Codable {
        let entries: [MCPCallLogEntry]
    }

    func listMCPStarterServers() async throws -> [MCPStarterServer] {
        let data = try await get("/settings/connections/starter_servers")
        let decoded = try JSONDecoder().decode(StarterServersResponse.self, from: data)
        return decoded.starterServers
    }

    func listMCPConnections() async throws -> [MCPConnection] {
        let data = try await get("/settings/connections")
        let decoded = try JSONDecoder().decode(ConnectionsListResponse.self, from: data)
        return decoded.connections
    }

    /// Begin an OAuth flow against an MCP server. The returned
    /// ``authorizationUrl`` should be opened in the user's default
    /// browser; the OAuth provider will redirect through the local
    /// FastAPI callback, which in turn sends the user back to Basil
    /// via the ``basil://mcp/connection_complete`` URL scheme.
    func startMCPOAuth(
        serverUrl: String,
        friendlyName: String,
        description: String? = nil,
        connectionId: String? = nil
    ) async throws -> URL {
        let body = StartOAuthRequest(
            serverUrl: serverUrl,
            friendlyName: friendlyName,
            description: description,
            connectionId: connectionId
        )
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/start_oauth", body: payload)
        let decoded = try JSONDecoder().decode(StartOAuthResponse.self, from: data)
        guard let url = URL(string: decoded.authorizationUrl) else {
            throw APIError.invalidResponse
        }
        return url
    }

    /// Register an MCP server whose bearer token will be stored by the Swift
    /// client directly in Keychain. This exists for hosted MCP servers that
    /// support streamable HTTP but do not support OAuth Dynamic Client
    /// Registration (for example, GitHub's official remote MCP server).
    func registerManualTokenMCPConnection(
        serverUrl: String,
        friendlyName: String,
        description: String? = nil
    ) async throws -> MCPConnection {
        let body = RegisterManualTokenConnectionRequest(
            serverUrl: serverUrl,
            friendlyName: friendlyName,
            description: description
        )
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/manual_token", body: payload)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    func startGitHubDeviceFlow(
        serverUrl: String,
        friendlyName: String = "GitHub",
        description: String? = nil,
        connectionId: String? = nil
    ) async throws -> GitHubDeviceFlowStartResponse {
        let body = GitHubDeviceFlowStartRequest(
            friendlyName: friendlyName,
            serverUrl: serverUrl,
            description: description,
            connectionId: connectionId
        )
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/github/start_device_flow", body: payload)
        return try JSONDecoder().decode(GitHubDeviceFlowStartResponse.self, from: data)
    }

    func pollGitHubDeviceFlow(deviceCode: String) async throws -> GitHubDeviceFlowPollResponse {
        let body = GitHubDeviceFlowPollRequest(deviceCode: deviceCode)
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/github/poll_device_flow", body: payload)
        return try JSONDecoder().decode(GitHubDeviceFlowPollResponse.self, from: data)
    }

    /// Start the Slack OAuth PKCE flow. Slack's hosted MCP server does
    /// not support Dynamic Client Registration; this endpoint returns
    /// an authorization URL that the caller opens in the user's
    /// browser. Slack redirects back to ``basil://mcp/slack_oauth_callback``,
    /// which the AppDelegate forwards to ``completeSlackOAuth``.
    func startSlackOAuth(
        serverUrl: String,
        friendlyName: String = "Slack",
        description: String? = nil,
        requestedScopes: [String]? = nil,
        connectionId: String? = nil
    ) async throws -> SlackOAuthStartResponse {
        let body = SlackOAuthStartRequest(
            friendlyName: friendlyName,
            serverUrl: serverUrl,
            description: description,
            requestedScopes: requestedScopes,
            connectionId: connectionId
        )
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/slack/start_oauth", body: payload)
        return try JSONDecoder().decode(SlackOAuthStartResponse.self, from: data)
    }

    /// Forward the ``code`` and ``state`` Slack delivered to the
    /// custom URI callback so the local backend can exchange them
    /// for tokens, persist the connection, and push the tokens to
    /// Keychain over the WebSocket bridge.
    func completeSlackOAuth(state: String, code: String) async throws -> SlackOAuthCompleteResponse {
        let body = SlackOAuthCompleteRequest(state: state, code: code)
        let payload = try JSONEncoder().encode(body)
        let data = try await postJSON("/settings/connections/slack/complete_oauth", body: payload)
        return try JSONDecoder().decode(SlackOAuthCompleteResponse.self, from: data)
    }

    /// Force a fresh fetch of the live tool catalog for one connection
    /// (also updates the server-side cache that drives this tab).
    func refreshMCPTools(connectionId: String) async throws -> MCPConnection {
        let data = try await get("/settings/connections/\(connectionId)/tools")
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    func updateMCPToolPolicies(
        connectionId: String,
        policies: [MCPToolPolicyUpdate]
    ) async throws -> MCPConnection {
        let body = ToolPolicyBulkUpdate(policies: policies)
        let payload = try JSONEncoder().encode(body)
        let data = try await put("/settings/connections/\(connectionId)/policy", data: payload)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    func updateMCPConnectionMetadata(
        connectionId: String,
        friendlyName: String,
        description: String?
    ) async throws -> MCPConnection {
        let body = ConnectionMetadataUpdateRequest(
            friendlyName: friendlyName,
            description: description
        )
        let payload = try JSONEncoder().encode(body)
        let data = try await put("/settings/connections/\(connectionId)/metadata", data: payload)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    func checkMCPConnectionStatus(connectionId: String) async throws -> ConnectionStatusResponse {
        let data = try await post("/settings/connections/\(connectionId)/status", body: Data())
        return try JSONDecoder().decode(ConnectionStatusResponse.self, from: data)
    }

    func deleteMCPConnection(connectionId: String) async throws {
        _ = try await delete("/settings/connections/\(connectionId)")
    }

    func fetchMCPCallLog(connectionId: String? = nil, limit: Int = 100) async throws -> [MCPCallLogEntry] {
        var path = "/settings/connections/call_log?limit=\(limit)"
        if let id = connectionId {
            path += "&connection_id=\(id)"
        }
        let data = try await get(path)
        let decoded = try JSONDecoder().decode(CallLogResponse.self, from: data)
        return decoded.entries
    }

    /// POST helper that mirrors the GET/PUT helpers in
    /// `APIClient_networking.swift` for endpoints that take a JSON
    /// body. Kept private to this file to avoid widening the public
    /// APIClient surface for a single use case.
    private func postJSON(_ endpoint: String, body: Data) async throws -> Data {
        return try await post(endpoint, body: body)
    }
}
