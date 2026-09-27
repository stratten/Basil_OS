import Foundation

// MARK: - Provider Profiles (Package 5C.2) API

extension APIClient {

    struct ProviderProfileWorkspaceGrantSummary: Codable, Identifiable, Hashable {
        let id: String
        let canonicalWorkspaceRoot: String
        let status: String
        let workspaceLabel: String
        let description: String?
        let routingHints: [String]
        let revision: Int

        enum CodingKeys: String, CodingKey {
            case id
            case canonicalWorkspaceRoot = "canonical_workspace_root"
            case status
            case workspaceLabel = "workspace_label"
            case description
            case routingHints = "routing_hints"
            case revision
        }
    }

    struct ProviderProfileSummary: Codable, Identifiable, Hashable {
        let id: String
        let displayName: String
        let status: String
        let capabilityState: String
        let description: String?
        let routingHints: [String]
        let revision: Int
        let hasObservedCapabilities: Bool
        let activeWorkspaceGrants: [ProviderProfileWorkspaceGrantSummary]
        let isStructurallyValid: Bool
        let validationError: String?
        let createdAt: String
        let updatedAt: String

        enum CodingKeys: String, CodingKey {
            case id
            case displayName = "display_name"
            case status
            case capabilityState = "capability_state"
            case description
            case routingHints = "routing_hints"
            case revision
            case hasObservedCapabilities = "has_observed_capabilities"
            case activeWorkspaceGrants = "active_workspace_grants"
            case isStructurallyValid = "is_structurally_valid"
            case validationError = "validation_error"
            case createdAt = "created_at"
            case updatedAt = "updated_at"
        }
    }

    struct ProviderProfileConfiguration: Codable, Identifiable, Hashable {
        let id: String
        let displayName: String
        let status: String
        let capabilityState: String
        let description: String?
        let routingHints: [String]
        let revision: Int
        let hasObservedCapabilities: Bool
        let activeWorkspaceGrants: [ProviderProfileWorkspaceGrantSummary]
        let isStructurallyValid: Bool
        let validationError: String?
        let createdAt: String
        let updatedAt: String
        let launchArgv: [String]
        let environmentAllowlist: [String]
        let authenticationMethodId: String?

        enum CodingKeys: String, CodingKey {
            case id
            case displayName = "display_name"
            case status
            case capabilityState = "capability_state"
            case description
            case routingHints = "routing_hints"
            case revision
            case hasObservedCapabilities = "has_observed_capabilities"
            case activeWorkspaceGrants = "active_workspace_grants"
            case isStructurallyValid = "is_structurally_valid"
            case validationError = "validation_error"
            case createdAt = "created_at"
            case updatedAt = "updated_at"
            case launchArgv = "launch_argv"
            case environmentAllowlist = "environment_allowlist"
            case authenticationMethodId = "authentication_method_id"
        }
    }

    struct ProviderProfileConfigurationRequest: Codable, Hashable {
        let displayName: String
        let launchArgv: [String]
        let environmentAllowlist: [String]
        let authenticationMethodId: String?
        let description: String?
        let routingHints: [String]

        enum CodingKeys: String, CodingKey {
            case displayName = "display_name"
            case launchArgv = "launch_argv"
            case environmentAllowlist = "environment_allowlist"
            case authenticationMethodId = "authentication_method_id"
            case description
            case routingHints = "routing_hints"
        }
    }

    struct ProviderProfileUpdateRequest: Codable, Hashable {
        let expectedRevision: Int
        let displayName: String
        let launchArgv: [String]
        let environmentAllowlist: [String]
        let authenticationMethodId: String?
        let description: String?
        let routingHints: [String]

        enum CodingKeys: String, CodingKey {
            case expectedRevision = "expected_revision"
            case displayName = "display_name"
            case launchArgv = "launch_argv"
            case environmentAllowlist = "environment_allowlist"
            case authenticationMethodId = "authentication_method_id"
            case description
            case routingHints = "routing_hints"
        }
    }

    struct ProviderProfileRevisionRequest: Codable, Hashable {
        let expectedRevision: Int

        enum CodingKeys: String, CodingKey {
            case expectedRevision = "expected_revision"
        }
    }

    struct WorkspaceGrantCreateRequest: Codable, Hashable {
        let canonicalWorkspaceRoot: String
        let workspaceLabel: String
        let description: String?
        let routingHints: [String]

        enum CodingKeys: String, CodingKey {
            case canonicalWorkspaceRoot = "canonical_workspace_root"
            case workspaceLabel = "workspace_label"
            case description
            case routingHints = "routing_hints"
        }
    }

    struct WorkspaceGrantUpdateRequest: Codable, Hashable {
        let expectedRevision: Int
        let workspaceLabel: String
        let description: String?
        let routingHints: [String]

        enum CodingKeys: String, CodingKey {
            case expectedRevision = "expected_revision"
            case workspaceLabel = "workspace_label"
            case description
            case routingHints = "routing_hints"
        }
    }

    private struct ProviderProfilesListResponse: Codable {
        let profiles: [ProviderProfileSummary]
    }

    func listProviderProfiles() async throws -> [ProviderProfileSummary] {
        let data = try await get("/settings/provider-profiles")
        let decoded = try JSONDecoder().decode(ProviderProfilesListResponse.self, from: data)
        return decoded.profiles
    }

    func getProviderProfileConfiguration(profileId: String) async throws -> ProviderProfileConfiguration {
        let data = try await get("/settings/provider-profiles/\(profileId)")
        return try JSONDecoder().decode(ProviderProfileConfiguration.self, from: data)
    }

    func createProviderProfile(
        configuration: ProviderProfileConfigurationRequest
    ) async throws -> ProviderProfileConfiguration {
        let data = try await post(
            "/settings/provider-profiles",
            body: JSONEncoder().encode(configuration)
        )
        return try JSONDecoder().decode(ProviderProfileConfiguration.self, from: data)
    }

    func updateProviderProfile(
        profileId: String,
        expectedRevision: Int,
        configuration: ProviderProfileConfigurationRequest
    ) async throws -> ProviderProfileConfiguration {
        let body = ProviderProfileUpdateRequest(
            expectedRevision: expectedRevision,
            displayName: configuration.displayName,
            launchArgv: configuration.launchArgv,
            environmentAllowlist: configuration.environmentAllowlist,
            authenticationMethodId: configuration.authenticationMethodId,
            description: configuration.description,
            routingHints: configuration.routingHints
        )
        let data = try await put(
            "/settings/provider-profiles/\(profileId)",
            data: JSONEncoder().encode(body)
        )
        return try JSONDecoder().decode(ProviderProfileConfiguration.self, from: data)
    }

    func setProviderProfileStatus(
        profileId: String,
        expectedRevision: Int,
        enabled: Bool
    ) async throws -> ProviderProfileConfiguration {
        let endpoint = enabled ? "enable" : "disable"
        let body = ProviderProfileRevisionRequest(expectedRevision: expectedRevision)
        let data = try await post(
            "/settings/provider-profiles/\(profileId)/\(endpoint)",
            body: JSONEncoder().encode(body)
        )
        return try JSONDecoder().decode(ProviderProfileConfiguration.self, from: data)
    }

    func removeProviderProfile(profileId: String, expectedRevision: Int) async throws {
        _ = try await delete(
            "/settings/provider-profiles/\(profileId)?expected_revision=\(expectedRevision)"
        )
    }

    func createWorkspaceGrant(
        profileId: String,
        canonicalWorkspaceRoot: String,
        workspaceLabel: String,
        description: String?,
        routingHints: [String]
    ) async throws -> ProviderProfileWorkspaceGrantSummary {
        let body = WorkspaceGrantCreateRequest(
            canonicalWorkspaceRoot: canonicalWorkspaceRoot,
            workspaceLabel: workspaceLabel,
            description: description,
            routingHints: routingHints
        )
        let data = try await post(
            "/settings/provider-profiles/\(profileId)/workspace-grants",
            body: JSONEncoder().encode(body)
        )
        return try JSONDecoder().decode(ProviderProfileWorkspaceGrantSummary.self, from: data)
    }

    func updateWorkspaceGrant(
        profileId: String,
        grantId: String,
        expectedRevision: Int,
        workspaceLabel: String,
        description: String?,
        routingHints: [String]
    ) async throws -> ProviderProfileWorkspaceGrantSummary {
        let body = WorkspaceGrantUpdateRequest(
            expectedRevision: expectedRevision,
            workspaceLabel: workspaceLabel,
            description: description,
            routingHints: routingHints
        )
        let data = try await put(
            "/settings/provider-profiles/\(profileId)/workspace-grants/\(grantId)",
            data: JSONEncoder().encode(body)
        )
        return try JSONDecoder().decode(ProviderProfileWorkspaceGrantSummary.self, from: data)
    }

    func revokeWorkspaceGrant(
        profileId: String,
        grantId: String,
        expectedRevision: Int
    ) async throws {
        _ = try await delete(
            "/settings/provider-profiles/\(profileId)/workspace-grants/\(grantId)?expected_revision=\(expectedRevision)"
        )
    }
}
