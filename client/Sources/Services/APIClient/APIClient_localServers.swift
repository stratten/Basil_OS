import Foundation

// MARK: - Local servers (programs on this Mac)
//
// Shapes mirror `CompanionStatusDTO`, `LocalServerDTO`, `CompanionSpecRequest` and `RegisterLocalServerRequest` in
// `backend/src/api/routes/connections/models.py`. The routes live in `backend/src/api/routes/connections/local_server_routes.py`.

extension APIClient {

    /// The live state of a local server's background program, as the backend reports it. `logTail` is only filled while the status is `failed`.
    struct LocalServerCompanionStatus: Codable, Hashable {
        let commandSummary: String
        let startWithBasil: Bool
        let fixedPort: Int?
        let secretEnv: [String]
        let status: String
        let port: Int?
        let lastError: String?
        let logTail: String
        let restartCount: Int
        /// What the program's own status page says. All optional so an older backend, or a program with no status page, still decodes. `actionValue` is a code to scan; the backend holds it in memory only.
        var hasProbe: Bool? = nil
        var healthPhase: String? = nil
        var healthMessage: String? = nil
        var actionKind: String? = nil
        var actionValue: String? = nil
        var actionExpiresAt: String? = nil

        enum CodingKeys: String, CodingKey {
            case commandSummary = "command_summary"
            case startWithBasil = "start_with_basil"
            case fixedPort = "fixed_port"
            case secretEnv = "secret_env"
            case status
            case port
            case lastError = "last_error"
            case logTail = "log_tail"
            case restartCount = "restart_count"
            case hasProbe = "has_probe"
            case healthPhase = "health_phase"
            case healthMessage = "health_message"
            case actionKind = "action_kind"
            case actionValue = "action_value"
            case actionExpiresAt = "action_expires_at"
        }
    }

    /// A program a local server's setup recipe needs installed. `installCommand` is the exact command Basil runs when the person chooses Install.
    struct LocalServerRequirementStatus: Codable, Hashable {
        let name: String
        let reason: String
        let forMethod: String
        let installCommand: String?

        enum CodingKeys: String, CodingKey {
            case name
            case reason
            case forMethod = "for_method"
            case installCommand = "install_command"
        }
    }

    /// One file a recipe puts in place, with every address, hash, commit and command that may produce it.
    struct LocalServerArtifactStatus: Codable, Hashable {
        let name: String
        let expects: String
        let ready: Bool
        let sources: [String]
    }

    /// A local server's setup recipe and how far its preparation has got.
    struct LocalServerInstallStatus: Codable, Hashable {
        let phase: String
        let message: String
        let ready: Bool
        let active: Bool
        let artifact: String?
        let requirement: String?
        let canInstall: Bool
        let detail: String?
        let requirements: [LocalServerRequirementStatus]
        let artifacts: [LocalServerArtifactStatus]

        enum CodingKeys: String, CodingKey {
            case phase
            case message
            case ready
            case active
            case artifact
            case requirement
            case canInstall = "can_install"
            case detail
            case requirements
            case artifacts
        }
    }

    /// What the Connections tab knows about a connection that is a program on this Mac. Secret names only; a value never leaves the Keychain.
    struct LocalServerDetails: Codable, Hashable {
        let commandSummary: String
        let sourceUrl: String?
        let secretEnv: [String]
        let companion: LocalServerCompanionStatus?
        /// Present only when the server was added with a setup recipe.
        var install: LocalServerInstallStatus? = nil

        enum CodingKeys: String, CodingKey {
            case commandSummary = "command_summary"
            case sourceUrl = "source_url"
            case secretEnv = "secret_env"
            case companion
            case install
        }
    }

    /// A background program that must run beside a local server.
    struct LocalServerCompanionRegistration: Codable, Equatable {
        let command: String
        let args: [String]
        let cwd: String?
        let env: [String: String]
        let secretEnv: [String]
        let startWithBasil: Bool
        let fixedPort: Int?
        /// The status page Basil reads to tell whether the program is ready, as the backend's probe object. Passed through untouched.
        var probe: LocalServerJSONValue? = nil

        enum CodingKeys: String, CodingKey {
            case command
            case args
            case cwd
            case env
            case secretEnv = "secret_env"
            case startWithBasil = "start_with_basil"
            case fixedPort = "fixed_port"
            case probe
        }
    }

    /// The definition the Add Local Server form sends. `connectionId` is filled in by the view model just before the request is made.
    struct LocalServerRegistration: Codable, Equatable {
        let friendlyName: String
        let description: String?
        let command: String
        let args: [String]
        let cwd: String?
        let env: [String: String]
        let sourceUrl: String?
        let secretEnv: [String]
        let companion: LocalServerCompanionRegistration?
        var connectionId: String?
        /// The setup recipe, as the backend's install object. Passed through untouched.
        var install: LocalServerJSONValue? = nil

        enum CodingKeys: String, CodingKey {
            case friendlyName = "friendly_name"
            case description
            case command
            case args
            case cwd
            case env
            case sourceUrl = "source_url"
            case secretEnv = "secret_env"
            case companion
            case connectionId = "connection_id"
            case install
        }
    }

    private struct LocalServerRequirementInstallRequest: Encodable {
        let name: String
        let command: String
    }

    private struct LocalServerCompanionSettingsRequest: Encodable {
        let startWithBasil: Bool

        enum CodingKeys: String, CodingKey {
            case startWithBasil = "start_with_basil"
        }
    }

    /// Adds the program, starts its background program when it has one, lists its tools, and returns the connection. A failure removes the record again on the backend.
    func registerLocalServer(_ registration: LocalServerRegistration) async throws -> MCPConnection {
        let payload = try JSONEncoder().encode(registration)
        let data = try await post("/settings/connections/local_server", body: payload, timeout: 240, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// Starts the background program now. A start that fails is reported in the returned connection's `localServer.companion`, not as an error.
    func startLocalServerCompanion(connectionId: String) async throws -> MCPConnection {
        let data = try await post("/settings/connections/local_server/\(connectionId)/companion/start", body: Data(), timeout: 240, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// Stops the background program and keeps it stopped until it is started again or its server is used.
    func stopLocalServerCompanion(connectionId: String) async throws -> MCPConnection {
        let data = try await post("/settings/connections/local_server/\(connectionId)/companion/stop", body: Data(), timeout: 60, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// Chooses whether the background program starts whenever Basil starts or the first time its server is used.
    func setLocalServerCompanionStartWithBasil(connectionId: String, startWithBasil: Bool) async throws -> MCPConnection {
        let payload = try JSONEncoder().encode(LocalServerCompanionSettingsRequest(startWithBasil: startWithBasil))
        let data = try await put("/settings/connections/local_server/\(connectionId)/companion", data: payload)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// The server's current setup and background-program state. Read-only, so a failure is not logged as an error.
    func localServerStatus(connectionId: String) async throws -> MCPConnection {
        let data = try await get("/settings/connections/local_server/\(connectionId)/status", quiet: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// Starts getting everything the recipe lists, in the background, and returns at once with the first state.
    func prepareLocalServer(connectionId: String) async throws -> MCPConnection {
        let data = try await post("/settings/connections/local_server/\(connectionId)/prepare", body: Data(), timeout: 60, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    func cancelPrepareLocalServer(connectionId: String) async throws -> MCPConnection {
        let data = try await post("/settings/connections/local_server/\(connectionId)/prepare/cancel", body: Data(), timeout: 60, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }

    /// Installs one program the recipe needs. `command` must be the text the person saw on the button; the backend refuses it if the recipe's command differs.
    func installLocalServerRequirement(connectionId: String, name: String, command: String) async throws -> MCPConnection {
        let payload = try JSONEncoder().encode(LocalServerRequirementInstallRequest(name: name, command: command))
        let data = try await post("/settings/connections/local_server/\(connectionId)/requirements/install", body: payload, timeout: 60, surfaceServerDetail: true)
        return try JSONDecoder().decode(MCPConnection.self, from: data)
    }
}
