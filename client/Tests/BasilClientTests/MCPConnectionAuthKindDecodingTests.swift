import XCTest
@testable import BasilClient

final class MCPConnectionAuthKindDecodingTests: XCTestCase {
    private func connectionJSON(extraFields: String) -> Data {
        Data(
            """
            {
              "id": "conn-1",
              "friendly_name": "Linear",
              "description": null,
              "server_url": "https://mcp.linear.app/mcp",
              "enabled": true,
              "registered_at": "2026-10-01T12:00:00",
              "last_tool_refresh_at": null,
              "last_connection_check_at": null,
              "last_connection_status": "needs_reconnect",
              "last_connection_status_message": "MCP server rejected credentials with HTTP 401",
              "server_name": null,
              "server_instructions": null,
              \(extraFields)
              "tools": []
            }
            """.utf8
        )
    }

    func testDecodesAuthKindFromBackend() throws {
        let connection = try JSONDecoder().decode(
            APIClient.MCPConnection.self,
            from: connectionJSON(extraFields: "\"auth_kind\": \"oauth\",")
        )
        XCTAssertEqual(connection.authKind, "oauth")
        XCTAssertEqual(connection.lastConnectionStatus, "needs_reconnect")
    }

    func testOlderBackendWithoutAuthKindStillDecodes() throws {
        let connection = try JSONDecoder().decode(
            APIClient.MCPConnection.self,
            from: connectionJSON(extraFields: "")
        )
        XCTAssertNil(connection.authKind)
        XCTAssertEqual(connection.friendlyName, "Linear")
    }
}
