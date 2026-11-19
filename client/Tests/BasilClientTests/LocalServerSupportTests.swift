import XCTest
@testable import BasilClient

final class LocalServerSupportTests: XCTestCase {
    private func registration(secretEnv: [String], companionSecretEnv: [String]?) -> APIClient.LocalServerRegistration {
        APIClient.LocalServerRegistration(
            friendlyName: "WhatsApp",
            description: nil,
            command: "uv",
            args: [],
            cwd: nil,
            env: [:],
            sourceUrl: nil,
            secretEnv: secretEnv,
            companion: companionSecretEnv.map {
                APIClient.LocalServerCompanionRegistration(command: "bridge", args: [], cwd: nil, env: [:], secretEnv: $0, startWithBasil: true, fixedPort: nil)
            },
            connectionId: nil
        )
    }

    private func connection(companionStatus: String?, lastError: String?) -> APIClient.MCPConnection {
        let companion = companionStatus.map {
            """
            {"command_summary": "bridge", "start_with_basil": true, "fixed_port": null, "secret_env": [], "status": "\($0)", "port": null, "last_error": \(lastError.map { "\"\($0)\"" } ?? "null"), "log_tail": "", "restart_count": 0}
            """
        } ?? "null"
        let json = """
        {"id": "c-1", "friendly_name": "WhatsApp", "description": null, "server_url": "stdio://uv", "enabled": true,
         "registered_at": "2026-11-17T12:00:00", "last_tool_refresh_at": null, "last_connection_check_at": null,
         "last_connection_status": null, "last_connection_status_message": null, "server_name": null, "server_instructions": null,
         "auth_kind": "local", "tools": [],
         "local_server": {"command_summary": "uv run", "source_url": null, "secret_env": [], "companion": \(companion)}}
        """
        return try! JSONDecoder().decode(APIClient.MCPConnection.self, from: Data(json.utf8))
    }

    func testTheKeychainAccountMatchesTheBackendFormat() {
        XCTAssertEqual(LocalServerSecretKey.account(connectionId: "abc", name: "API_KEY"), "abc.env.API_KEY")
    }

    func testDeclaredNamesListTheServerFirstAndEachNameOnce() {
        let names = LocalServerSecretKey.declaredNames(in: registration(secretEnv: ["TOKEN", "API_KEY"], companionSecretEnv: ["TOKEN", "BRIDGE"]))
        XCTAssertEqual(names, ["TOKEN", "API_KEY", "BRIDGE"])
    }

    func testDeclaredNamesWithoutACompanionAreTheServersOwn() {
        XCTAssertEqual(LocalServerSecretKey.declaredNames(in: registration(secretEnv: ["API_KEY"], companionSecretEnv: nil)), ["API_KEY"])
        XCTAssertEqual(LocalServerSecretKey.declaredNames(in: registration(secretEnv: [], companionSecretEnv: nil)), [])
    }

    func testDeclaredNamesOfAnExistingServerIncludeItsBackgroundProgram() throws {
        let details = try XCTUnwrap(connection(companionStatus: "running", lastError: nil).localServer)
        XCTAssertEqual(LocalServerSecretKey.declaredNames(in: details), [])
    }

    func testAFailedBackgroundProgramReportsItsReason() {
        XCTAssertEqual(
            LocalServerCompanionMessages.failure(in: connection(companionStatus: "failed", lastError: "exited with code 1")),
            "exited with code 1"
        )
    }

    func testAFailedBackgroundProgramWithoutAReasonStillSaysSo() {
        XCTAssertEqual(
            LocalServerCompanionMessages.failure(in: connection(companionStatus: "failed", lastError: nil)),
            "The background program for WhatsApp stopped unexpectedly."
        )
    }

    func testAMissingSecretIsReported() {
        XCTAssertEqual(
            LocalServerCompanionMessages.failure(in: connection(companionStatus: "needs_secrets", lastError: nil)),
            "The background program for WhatsApp is missing a secret value."
        )
    }

    func testARunningOrStartingOrAbsentBackgroundProgramHasNoFailure() {
        XCTAssertNil(LocalServerCompanionMessages.failure(in: connection(companionStatus: "running", lastError: nil)))
        XCTAssertNil(LocalServerCompanionMessages.failure(in: connection(companionStatus: "starting", lastError: nil)))
        XCTAssertNil(LocalServerCompanionMessages.failure(in: connection(companionStatus: nil, lastError: nil)))
    }

    func testAMissingValueErrorNamesTheSecret() {
        XCTAssertEqual(LocalServerSecretError.missingValue("API_KEY").localizedDescription, "A value for API_KEY is required.")
    }
}
