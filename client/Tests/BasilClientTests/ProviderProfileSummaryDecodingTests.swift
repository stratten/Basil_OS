import XCTest
@testable import BasilClient

final class ProviderProfileSummaryDecodingTests: XCTestCase {

    func testDecodesAWellFormedValidProfileWithAnActiveGrant() throws {
        let json = """
        {
            "profiles": [
                {
                    "id": "profile-1",
                    "display_name": "Fixture Provider",
                    "status": "enabled",
                    "capability_state": "unverified",
                    "description": "Fixture runtime",
                    "routing_hints": ["Swift", "local"],
                    "revision": 3,
                    "has_observed_capabilities": false,
                    "active_workspace_grants": [
                        {
                            "id": "grant-1",
                            "canonical_workspace_root": "/tmp/workspace",
                            "status": "active",
                            "workspace_label": "Fixture workspace",
                            "description": "Disposable test root",
                            "routing_hints": ["fixture"],
                            "revision": 2
                        }
                    ],
                    "is_structurally_valid": true,
                    "validation_error": null,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00"
                }
            ]
        }
        """.data(using: .utf8)!

        struct Response: Codable {
            let profiles: [APIClient.ProviderProfileSummary]
        }

        let decoded = try JSONDecoder().decode(Response.self, from: json)

        XCTAssertEqual(decoded.profiles.count, 1)
        let profile = decoded.profiles[0]
        XCTAssertEqual(profile.id, "profile-1")
        XCTAssertEqual(profile.displayName, "Fixture Provider")
        XCTAssertEqual(profile.status, "enabled")
        XCTAssertEqual(profile.description, "Fixture runtime")
        XCTAssertEqual(profile.routingHints, ["Swift", "local"])
        XCTAssertEqual(profile.revision, 3)
        XCTAssertFalse(profile.hasObservedCapabilities)
        XCTAssertEqual(profile.activeWorkspaceGrants.count, 1)
        XCTAssertEqual(profile.activeWorkspaceGrants[0].canonicalWorkspaceRoot, "/tmp/workspace")
        XCTAssertEqual(profile.activeWorkspaceGrants[0].workspaceLabel, "Fixture workspace")
        XCTAssertEqual(profile.activeWorkspaceGrants[0].routingHints, ["fixture"])
        XCTAssertEqual(profile.activeWorkspaceGrants[0].revision, 2)
        XCTAssertTrue(profile.isStructurallyValid)
        XCTAssertNil(profile.validationError)
    }

    func testDecodesAnInvalidProfileWithNoActiveGrantsAndAValidationError() throws {
        let json = """
        {
            "profiles": [
                {
                    "id": "profile-2",
                    "display_name": "Broken Provider",
                    "status": "enabled",
                    "capability_state": "unverified",
                    "description": null,
                    "routing_hints": [],
                    "revision": 0,
                    "has_observed_capabilities": true,
                    "active_workspace_grants": [],
                    "is_structurally_valid": false,
                    "validation_error": "provider profile 'profile-2' has no launch_argv",
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00"
                }
            ]
        }
        """.data(using: .utf8)!

        struct Response: Codable {
            let profiles: [APIClient.ProviderProfileSummary]
        }

        let decoded = try JSONDecoder().decode(Response.self, from: json)

        let profile = decoded.profiles[0]
        XCTAssertTrue(profile.activeWorkspaceGrants.isEmpty)
        XCTAssertNil(profile.description)
        XCTAssertTrue(profile.routingHints.isEmpty)
        XCTAssertEqual(profile.revision, 0)
        XCTAssertFalse(profile.isStructurallyValid)
        XCTAssertTrue(profile.hasObservedCapabilities)
        XCTAssertEqual(profile.validationError, "provider profile 'profile-2' has no launch_argv")
    }

    func testDecodesAnEmptyProfileList() throws {
        let json = "{\"profiles\": []}".data(using: .utf8)!

        struct Response: Codable {
            let profiles: [APIClient.ProviderProfileSummary]
        }

        let decoded = try JSONDecoder().decode(Response.self, from: json)

        XCTAssertTrue(decoded.profiles.isEmpty)
    }

    func testEncodesNonSecretProviderAndWorkspaceConfigurationRequests() throws {
        let profileConfiguration = APIClient.ProviderProfileConfigurationRequest(
            displayName: "Fixture Provider",
            launchArgv: ["/usr/bin/env", "fixture-acp"],
            environmentAllowlist: ["PATH"],
            authenticationMethodId: "api-key",
            description: "Fixture-only provider",
            routingHints: ["Swift"]
        )
        let profileUpdate = APIClient.ProviderProfileUpdateRequest(
            expectedRevision: 4,
            displayName: profileConfiguration.displayName,
            launchArgv: profileConfiguration.launchArgv,
            environmentAllowlist: profileConfiguration.environmentAllowlist,
            authenticationMethodId: profileConfiguration.authenticationMethodId,
            description: profileConfiguration.description,
            routingHints: profileConfiguration.routingHints
        )
        let workspaceCreate = APIClient.WorkspaceGrantCreateRequest(
            canonicalWorkspaceRoot: "/tmp/workspace",
            workspaceLabel: "Fixture workspace",
            description: nil,
            routingHints: ["fixture"]
        )
        let workspaceUpdate = APIClient.WorkspaceGrantUpdateRequest(
            expectedRevision: 2,
            workspaceLabel: "Renamed fixture",
            description: "Updated metadata",
            routingHints: ["fixture", "temporary"]
        )

        let profileJSON = try jsonObject(profileUpdate)
        let workspaceCreateJSON = try jsonObject(workspaceCreate)
        let workspaceUpdateJSON = try jsonObject(workspaceUpdate)

        XCTAssertEqual(profileJSON["display_name"] as? String, "Fixture Provider")
        XCTAssertEqual(profileJSON["expected_revision"] as? Int, 4)
        XCTAssertEqual(profileJSON["routing_hints"] as? [String], ["Swift"])
        XCTAssertEqual(profileJSON["authentication_method_id"] as? String, "api-key")
        XCTAssertNil(profileJSON["credentials"])
        XCTAssertNil(profileJSON["token"])
        XCTAssertEqual(workspaceCreateJSON["canonical_workspace_root"] as? String, "/tmp/workspace")
        XCTAssertEqual(workspaceCreateJSON["routing_hints"] as? [String], ["fixture"])
        XCTAssertEqual(workspaceUpdateJSON["expected_revision"] as? Int, 2)
        XCTAssertEqual(workspaceUpdateJSON["routing_hints"] as? [String], ["fixture", "temporary"])
    }

    func testDecodesOptionalAuthenticationMethodIDFromProfileConfiguration() throws {
        let configuredJSON = """
        {
            "id": "profile-1",
            "display_name": "Fixture Provider",
            "status": "enabled",
            "capability_state": "unverified",
            "description": null,
            "routing_hints": [],
            "revision": 0,
            "has_observed_capabilities": false,
            "active_workspace_grants": [],
            "is_structurally_valid": true,
            "validation_error": null,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "launch_argv": ["/usr/bin/env", "fixture-acp"],
            "environment_allowlist": ["PATH"],
            "authentication_method_id": "api-key"
        }
        """.data(using: .utf8)!
        let legacyJSON = """
        {
            "id": "profile-2",
            "display_name": "Legacy Provider",
            "status": "enabled",
            "capability_state": "unverified",
            "description": null,
            "routing_hints": [],
            "revision": 0,
            "has_observed_capabilities": false,
            "active_workspace_grants": [],
            "is_structurally_valid": true,
            "validation_error": null,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "launch_argv": ["/usr/bin/env", "fixture-acp"],
            "environment_allowlist": ["PATH"]
        }
        """.data(using: .utf8)!

        let configured = try JSONDecoder().decode(APIClient.ProviderProfileConfiguration.self, from: configuredJSON)
        let legacy = try JSONDecoder().decode(APIClient.ProviderProfileConfiguration.self, from: legacyJSON)

        XCTAssertEqual(configured.authenticationMethodId, "api-key")
        XCTAssertNil(legacy.authenticationMethodId)
    }

    private func jsonObject<T: Encodable>(_ value: T) throws -> [String: Any] {
        let data = try JSONEncoder().encode(value)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}
