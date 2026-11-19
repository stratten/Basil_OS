import XCTest
@testable import BasilClient

final class MCPConnectionLocalServerDecodingTests: XCTestCase {
    private func connectionJSON(extraFields: String) -> Data {
        Data(
            """
            {
              "id": "conn-1",
              "friendly_name": "WhatsApp",
              "description": null,
              "server_url": "stdio://uv",
              "enabled": true,
              "registered_at": "2026-11-17T12:00:00",
              "last_tool_refresh_at": null,
              "last_connection_check_at": null,
              "last_connection_status": null,
              "last_connection_status_message": null,
              "server_name": null,
              "server_instructions": null,
              "auth_kind": "local",
              \(extraFields)
              "tools": []
            }
            """.utf8
        )
    }

    func testDecodesALocalServerWithABackgroundProgram() throws {
        let extra = """
        "local_server": {
          "command_summary": "uv run main.py",
          "source_url": "https://github.com/example/whatsapp-mcp",
          "secret_env": ["API_KEY"],
          "companion": {
            "command_summary": "/usr/local/bin/bridge --port {port}",
            "start_with_basil": true,
            "fixed_port": null,
            "secret_env": ["BRIDGE_TOKEN"],
            "status": "failed",
            "port": 51234,
            "last_error": "exited with code 1",
            "log_tail": "boom",
            "restart_count": 3
          }
        },
        """
        let connection = try JSONDecoder().decode(APIClient.MCPConnection.self, from: connectionJSON(extraFields: extra))

        let details = try XCTUnwrap(connection.localServer)
        XCTAssertEqual(details.commandSummary, "uv run main.py")
        XCTAssertEqual(details.sourceUrl, "https://github.com/example/whatsapp-mcp")
        XCTAssertEqual(details.secretEnv, ["API_KEY"])
        let companion = try XCTUnwrap(details.companion)
        XCTAssertEqual(companion.status, "failed")
        XCTAssertEqual(companion.port, 51234)
        XCTAssertNil(companion.fixedPort)
        XCTAssertEqual(companion.lastError, "exited with code 1")
        XCTAssertEqual(companion.logTail, "boom")
        XCTAssertEqual(companion.restartCount, 3)
        XCTAssertEqual(companion.secretEnv, ["BRIDGE_TOKEN"])
        XCTAssertTrue(companion.startWithBasil)
    }

    func testALocalServerWithoutABackgroundProgramDecodes() throws {
        let extra = """
        "local_server": {"command_summary": "npx server", "source_url": null, "secret_env": [], "companion": null},
        """
        let connection = try JSONDecoder().decode(APIClient.MCPConnection.self, from: connectionJSON(extraFields: extra))
        XCTAssertNil(connection.localServer?.companion)
        XCTAssertEqual(connection.localServer?.commandSummary, "npx server")
    }

    func testAConnectionWithoutALocalServerDecodesToNil() throws {
        let connection = try JSONDecoder().decode(APIClient.MCPConnection.self, from: connectionJSON(extraFields: ""))
        XCTAssertNil(connection.localServer)
    }

    func testARegistrationEncodesTheBackendFieldNamesAndOmitsAbsentOptionals() throws {
        let registration = APIClient.LocalServerRegistration(
            friendlyName: "WhatsApp",
            description: nil,
            command: "uv",
            args: ["run", "main.py"],
            cwd: nil,
            env: ["LOG": "info"],
            sourceUrl: "https://github.com/example/whatsapp-mcp",
            secretEnv: ["API_KEY"],
            companion: APIClient.LocalServerCompanionRegistration(
                command: "bridge", args: ["{port}"], cwd: nil, env: [:], secretEnv: ["BRIDGE_TOKEN"], startWithBasil: false, fixedPort: nil
            ),
            connectionId: "c-1"
        )

        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(registration)) as? [String: Any])

        XCTAssertEqual(object["friendly_name"] as? String, "WhatsApp")
        XCTAssertEqual(object["source_url"] as? String, "https://github.com/example/whatsapp-mcp")
        XCTAssertEqual(object["secret_env"] as? [String], ["API_KEY"])
        XCTAssertEqual(object["connection_id"] as? String, "c-1")
        XCTAssertNil(object["cwd"])
        XCTAssertNil(object["description"])
        let companion = try XCTUnwrap(object["companion"] as? [String: Any])
        XCTAssertEqual(companion["start_with_basil"] as? Bool, false)
        XCTAssertEqual(companion["secret_env"] as? [String], ["BRIDGE_TOKEN"])
        XCTAssertNil(companion["fixed_port"])
        XCTAssertNil(object["secretValues"])
    }
}
