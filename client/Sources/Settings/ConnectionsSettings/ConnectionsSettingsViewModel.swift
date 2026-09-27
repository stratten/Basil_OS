import AppKit
import Foundation
import SwiftUI

/// State + actions for the Connections settings tab.
///
/// Mirrors the structure of ``GeneralSettingsViewModel``: a single
/// @MainActor ObservableObject backed by ``APIClient.shared`` that
/// exposes ``@Published`` slices for the SwiftUI view to render.
///
/// The MCP token Keychain plumbing is not driven from here — it is
/// handled silently by ``WebSocketService_MCP`` in response to backend
/// pushes during the OAuth flow. Once the user completes consent in
/// their browser, the system will receive a ``basil://mcp/connection_complete``
/// callback (see :file:`AppDelegate_MCPConnectionHandling.swift`),
/// which posts ``Notification.Name.mcpConnectionCompleted``; this
/// view model listens for that and refreshes the connection list.
@MainActor
final class ConnectionsSettingsViewModel: ObservableObject {

    @Published var connections: [APIClient.MCPConnection] = []
    @Published var starterServers: [APIClient.MCPStarterServer] = []
    @Published var callLogEntries: [APIClient.MCPCallLogEntry] = []

    @Published var isLoading: Bool = false
    @Published var isAddingConnection: Bool = false
    @Published var isLoadingCallLog: Bool = false

    @Published var errorMessage: String?
    @Published var statusMessage: String?

    @Published var pendingFlowFriendlyName: String?
    @Published var githubDeviceFlow: GitHubDeviceFlowState?
    @Published var isPollingGitHubDeviceFlow: Bool = false

    private let apiClient = APIClient.shared
    private var connectionCompletedObserver: NSObjectProtocol?
    private var deviceFlowTask: Task<Void, Never>?

    init() {
        connectionCompletedObserver = NotificationCenter.default.addObserver(
            forName: .mcpConnectionCompleted,
            object: nil,
            queue: .main
        ) { [weak self] note in
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                self.pendingFlowFriendlyName = nil
                if let info = note.userInfo,
                   let status = info["status"] as? String,
                   status != "ok",
                   let message = info["message"] as? String {
                    self.errorMessage = "Connection failed: \(message)"
                } else {
                    self.statusMessage = "Connection added. Fetching tools..."
                }
                await self.loadConnections()
                if let connectionId = note.userInfo?["connection_id"] as? String,
                   let connection = self.connections.first(where: { $0.id == connectionId }) {
                    await self.refreshTools(for: connection)
                }
            }
        }
        Task { await self.initialLoad() }
    }

    deinit {
        if let token = connectionCompletedObserver {
            NotificationCenter.default.removeObserver(token)
        }
    }

    func initialLoad() async {
        // `async let` child tasks are implicitly cancelled the instant this
        // function's scope exits if they haven't been awaited -- binding to
        // `_` without ever awaiting means all three network calls below were
        // being cancelled out from under themselves as soon as `initialLoad()`
        // returned, which is what actually produced the intermittent
        // `URLError.cancelled` failures (a race against how fast each request
        // happened to complete). Awaiting all three keeps them running
        // concurrently but ensures none are torn down before finishing.
        async let starters: Void = loadStarterServers()
        async let connections: Void = loadConnections()
        async let callLog: Void = loadCallLog()
        _ = await (starters, connections, callLog)
    }

    func loadStarterServers() async {
        do {
            self.starterServers = try await apiClient.listMCPStarterServers()
        } catch {
            #if DEBUG
            DevLogger.shared.warning(
                "Failed to load MCP starter servers: \(error)",
                context: "ConnectionsSettingsViewModel"
            )
            #endif
        }
    }

    func loadConnections() async {
        isLoading = true
        defer { isLoading = false }
        do {
            self.connections = try await apiClient.listMCPConnections()
        } catch {
            self.errorMessage = "Failed to load connections: \(error.localizedDescription)"
        }
    }

    func loadCallLog() async {
        isLoadingCallLog = true
        defer { isLoadingCallLog = false }
        do {
            self.callLogEntries = try await apiClient.fetchMCPCallLog(limit: 50)
        } catch {
            #if DEBUG
            DevLogger.shared.warning(
                "Failed to load MCP call log: \(error)",
                context: "ConnectionsSettingsViewModel"
            )
            #endif
        }
    }

    /// Open the OAuth authorization URL in the user's browser.
    /// The eventual ``basil://mcp/connection_complete`` callback is
    /// handled by the AppDelegate, which posts a notification this
    /// view model is observing.
    func startConnectionFlow(
        serverUrl: String,
        friendlyName: String,
        description: String? = nil
    ) async {
        isAddingConnection = true
        errorMessage = nil
        statusMessage = nil
        defer { isAddingConnection = false }

        do {
            let authURL = try await apiClient.startMCPOAuth(
                serverUrl: serverUrl,
                friendlyName: friendlyName,
                description: description
            )
            pendingFlowFriendlyName = friendlyName
            NSWorkspace.shared.open(authURL)
            statusMessage = "Complete sign-in in your browser to finish adding \(friendlyName)."
        } catch {
            errorMessage = "Could not start \(friendlyName) sign-in: \(error.localizedDescription)"
        }
    }

    /// Begin the Slack OAuth PKCE flow. Slack's hosted MCP server
    /// requires a Basil-owned Slack app configured as a public PKCE
    /// client; the backend builds the authorization URL with the
    /// configured ``client_id`` and the fixed
    /// ``basil://mcp/slack_oauth_callback`` redirect URI. Once the
    /// user consents in their browser, the AppDelegate completes the
    /// flow against the local backend, which posts the standard
    /// ``mcpConnectionCompleted`` notification this view model
    /// observes.
    func startSlackConnectionFlow(
        serverUrl: String,
        friendlyName: String = "Slack",
        description: String? = nil
    ) async {
        isAddingConnection = true
        errorMessage = nil
        statusMessage = nil
        defer { isAddingConnection = false }

        do {
            let response = try await apiClient.startSlackOAuth(
                serverUrl: serverUrl,
                friendlyName: friendlyName,
                description: description
            )
            guard let url = URL(string: response.authorizationUrl) else {
                errorMessage = "Slack returned an invalid authorization URL."
                return
            }
            pendingFlowFriendlyName = friendlyName
            NSWorkspace.shared.open(url)
            statusMessage = "Complete Slack sign-in in your browser to finish adding \(friendlyName)."
        } catch {
            errorMessage = "Could not start \(friendlyName) sign-in: \(error.localizedDescription)"
        }
    }

    /// Start GitHub's OAuth App device flow and poll until the user approves.
    /// GitHub's hosted MCP server does not support OAuth Dynamic Client
    /// Registration, but it does accept device-flow OAuth App tokens.
    func startGitHubDeviceFlow(
        serverUrl: String,
        friendlyName: String = "GitHub",
        description: String? = nil
    ) async {
        isAddingConnection = true
        isPollingGitHubDeviceFlow = false
        errorMessage = nil
        statusMessage = nil
        defer {
            isAddingConnection = false
            isPollingGitHubDeviceFlow = false
        }

        do {
            let flow = try await apiClient.startGitHubDeviceFlow(
                serverUrl: serverUrl,
                friendlyName: friendlyName,
                description: description
            )
            githubDeviceFlow = GitHubDeviceFlowState(
                deviceCode: flow.deviceCode,
                userCode: flow.userCode,
                verificationUri: flow.verificationUri,
                expiresIn: flow.expiresIn,
                interval: flow.interval,
                requestedScopes: flow.requestedScopes
            )
            statusMessage = "Enter code \(flow.userCode) on GitHub to authorize Basil."
            if let url = URL(string: flow.verificationUri) {
                NSWorkspace.shared.open(url)
            }
            isPollingGitHubDeviceFlow = true
            let task = Task { [weak self] in
                guard let self else { return }
                await self.pollGitHubDeviceFlowUntilComplete(deviceCode: flow.deviceCode, initialInterval: flow.interval)
            }
            deviceFlowTask = task
            await task.value
        } catch {
            githubDeviceFlow = nil
            errorMessage = "Could not start GitHub sign-in: \(error.localizedDescription)"
        }
    }

    private func pollGitHubDeviceFlowUntilComplete(deviceCode: String, initialInterval: Int) async {
        var interval = max(initialInterval, 5)

        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64(interval) * 1_000_000_000)
            do {
                let response = try await apiClient.pollGitHubDeviceFlow(deviceCode: deviceCode)
                if response.status == "pending" {
                    interval = max(response.interval ?? interval, 5)
                    statusMessage = "Waiting for GitHub authorization..."
                    continue
                }

                if response.status == "ok", let connection = response.connection {
                    githubDeviceFlow = nil
                    statusMessage = "GitHub connected. Fetching tools..."
                    replaceConnection(connection)
                    await refreshTools(for: connection)
                    return
                }

                githubDeviceFlow = nil
                errorMessage = response.message ?? "GitHub authorization returned an unexpected status: \(response.status)"
                return
            } catch {
                githubDeviceFlow = nil
                errorMessage = "GitHub authorization failed: \(error.localizedDescription)"
                return
            }
        }
    }

    /// Register a non-DCR MCP server and store its bearer token directly in
    /// Keychain. This is intentionally separate from ``startConnectionFlow``:
    /// OAuth/DCR servers never expose their token to the UI, while manual-token
    /// servers require explicit user-provided credentials.
    func registerManualTokenConnection(
        serverUrl: String,
        friendlyName: String,
        description: String? = nil,
        bearerToken: String
    ) async {
        isAddingConnection = true
        errorMessage = nil
        statusMessage = nil
        defer { isAddingConnection = false }

        do {
            let connection = try await apiClient.registerManualTokenMCPConnection(
                serverUrl: serverUrl,
                friendlyName: friendlyName,
                description: description
            )
            try AuthService.shared.storeMCPToken(
                connectionId: connection.id,
                accessToken: bearerToken
            )
            statusMessage = "Added \(connection.friendlyName). Fetching tools..."
            replaceConnection(connection)
            await refreshTools(for: connection)
        } catch {
            errorMessage = "Could not add \(friendlyName): \(error.localizedDescription)"
        }
    }

    /// Cancel an in-progress GitHub device-flow poll and clear its state.
    /// The native UI has never offered a cancel path either; this exists so
    /// the React bridge (settled decision 6) can add one without changing
    /// any other device-flow behavior.
    func cancelGitHubDeviceFlow() {
        deviceFlowTask?.cancel()
        deviceFlowTask = nil
        githubDeviceFlow = nil
        isPollingGitHubDeviceFlow = false
        isAddingConnection = false
        statusMessage = nil
    }

    func deleteConnection(_ connection: APIClient.MCPConnection) async {
        errorMessage = nil
        statusMessage = nil
        do {
            try await apiClient.deleteMCPConnection(connectionId: connection.id)
            statusMessage = "Removed \(connection.friendlyName)."
            await loadConnections()
        } catch {
            errorMessage = "Failed to remove \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func refreshTools(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        do {
            let updated = try await apiClient.refreshMCPTools(connectionId: connection.id)
            replaceConnection(updated)
            statusMessage = "Refreshed tool catalog: \(updated.tools.count) tools for \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not refresh \(connection.friendlyName) tools: \(error.localizedDescription)"
        }
    }

    func updateConnectionMetadata(
        for connection: APIClient.MCPConnection,
        friendlyName: String,
        description: String?
    ) async {
        errorMessage = nil
        do {
            let updated = try await apiClient.updateMCPConnectionMetadata(
                connectionId: connection.id,
                friendlyName: friendlyName,
                description: description
            )
            replaceConnection(updated)
            statusMessage = "Updated \(updated.friendlyName)."
        } catch {
            errorMessage = "Could not update \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func checkConnectionStatus(for connection: APIClient.MCPConnection) async {
        errorMessage = nil
        do {
            let response = try await apiClient.checkMCPConnectionStatus(connectionId: connection.id)
            replaceConnection(response.connection)
            if response.refreshedCredentials {
                statusMessage = "\(response.connection.friendlyName): \(response.message) Credentials were refreshed."
            } else {
                statusMessage = "\(response.connection.friendlyName): \(response.message)"
            }
        } catch {
            errorMessage = "Could not check \(connection.friendlyName): \(error.localizedDescription)"
        }
    }

    func updatePolicy(
        for connection: APIClient.MCPConnection,
        toolName: String,
        newPolicy: String
    ) async {
        errorMessage = nil
        do {
            let updated = try await apiClient.updateMCPToolPolicies(
                connectionId: connection.id,
                policies: [APIClient.MCPToolPolicyUpdate(toolName: toolName, policy: newPolicy)]
            )
            replaceConnection(updated)
        } catch {
            errorMessage = "Could not update \(toolName) policy: \(error.localizedDescription)"
        }
    }

    private func replaceConnection(_ updated: APIClient.MCPConnection) {
        if let idx = connections.firstIndex(where: { $0.id == updated.id }) {
            connections[idx] = updated
        } else {
            connections.append(updated)
        }
    }
}

extension Notification.Name {
    /// Posted by the AppDelegate when a ``basil://mcp/connection_complete``
    /// URL is received. ``userInfo`` carries ``status`` ('ok'/'error')
    /// and an optional ``message`` describing the failure.
    static let mcpConnectionCompleted = Notification.Name("BasilMCPConnectionCompleted")
}

struct GitHubDeviceFlowState: Equatable {
    let deviceCode: String
    let userCode: String
    let verificationUri: String
    let expiresIn: Int
    let interval: Int
    let requestedScopes: [String]
}
