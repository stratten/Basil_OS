import XCTest
@testable import BasilClient

@MainActor
final class ConnectionTokenConnectorTests: XCTestCase {
    private struct Boom: LocalizedError {
        let text: String
        var errorDescription: String? { text }
    }

    private final class Recorder {
        var registered: [(url: String, name: String, description: String?)] = []
        var storedTokens: [String: String] = [:]
        var verified: [String] = []
        var removed: [String] = []
        var deletedTokens: [String] = []
        var registerError: Error?
        var storeError: Error?
        var verifyError: Error?
        var toolNames: [String] = ["search", "create"]
    }

    private func connection(id: String, tools: [String]) throws -> APIClient.MCPConnection {
        let toolJSON = tools.map { #"{"name":"\#($0)","description":null,"is_read_only_hint":false,"policy":"always_ask"}"# }.joined(separator: ",")
        let json = """
        {"id":"\(id)","friendly_name":"Example","description":null,"server_url":"https://mcp.example.com/mcp","enabled":true,"registered_at":"2026-10-29T00:00:00Z","last_tool_refresh_at":null,"last_connection_check_at":null,"last_successful_use_at":null,"last_connection_status":null,"last_connection_status_message":null,"server_name":null,"server_instructions":null,"auth_kind":"manual_token","tools":[\(toolJSON)]}
        """
        return try JSONDecoder().decode(APIClient.MCPConnection.self, from: Data(json.utf8))
    }

    private func makeConnector(_ recorder: Recorder) -> ConnectionTokenConnector {
        let operations = ConnectionTokenConnector.Operations(
            register: { [self] url, name, description in
                if let error = recorder.registerError { throw error }
                recorder.registered.append((url, name, description))
                return try connection(id: "c-1", tools: [])
            },
            storeToken: { id, token in
                if let error = recorder.storeError { throw error }
                recorder.storedTokens[id] = token
            },
            verify: { [self] id in
                recorder.verified.append(id)
                if let error = recorder.verifyError { throw error }
                return try connection(id: id, tools: recorder.toolNames)
            },
            removeConnection: { recorder.removed.append($0) },
            deleteToken: { recorder.deletedTokens.append($0) }
        )
        return ConnectionTokenConnector(operations: operations)
    }

    func testSuccessRegistersStoresVerifiesAndReportsToolCount() async {
        let recorder = Recorder()
        let outcome = await makeConnector(recorder).connect(
            serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: "Docs", token: "sk-abc123"
        )

        XCTAssertEqual(outcome, .connected(connectionId: "c-1", toolCount: 2, friendlyName: "Example", description: "Docs"))
        XCTAssertEqual(recorder.registered.first?.url, "https://mcp.example.com/mcp")
        XCTAssertEqual(recorder.registered.first?.description, "Docs")
        XCTAssertEqual(recorder.storedTokens["c-1"], "sk-abc123")
        XCTAssertEqual(recorder.verified, ["c-1"])
        XCTAssertTrue(recorder.removed.isEmpty)
    }

    func testBearerPrefixAndWhitespaceAreRemovedBeforeStoring() async {
        let recorder = Recorder()
        _ = await makeConnector(recorder).connect(
            serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: nil, token: "  Bearer sk-abc123\n"
        )
        XCTAssertEqual(recorder.storedTokens["c-1"], "sk-abc123")
    }

    func testATokenThatMerelyStartsWithBearerIsLeftAlone() {
        XCTAssertEqual(ConnectionTokenConnector.cleanedToken("bearer123abc"), "bearer123abc")
        XCTAssertEqual(ConnectionTokenConnector.cleanedToken("BEARER\tabc"), "abc")
    }

    func testAnEmptyTokenFailsWithoutCallingTheBackend() async {
        let recorder = Recorder()
        for blank in ["", "   ", "Bearer ", "bearer   \n"] {
            let outcome = await makeConnector(recorder).connect(
                serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: nil, token: blank
            )
            XCTAssertEqual(outcome, .failed(message: "Enter the token first."))
        }
        XCTAssertTrue(recorder.registered.isEmpty)
    }

    func testARegistrationFailureStoresNothing() async {
        let recorder = Recorder()
        recorder.registerError = Boom(text: "backend offline")
        let outcome = await makeConnector(recorder).connect(
            serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: nil, token: "sk-abc123"
        )
        XCTAssertEqual(outcome, .failed(message: "Could not add Example: backend offline"))
        XCTAssertTrue(recorder.storedTokens.isEmpty)
        XCTAssertTrue(recorder.removed.isEmpty)
    }

    func testAKeychainFailureRemovesTheConnection() async {
        let recorder = Recorder()
        recorder.storeError = Boom(text: "denied")
        let outcome = await makeConnector(recorder).connect(
            serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: nil, token: "sk-abc123"
        )
        guard case .failed(let message) = outcome else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("Keychain"))
        XCTAssertEqual(recorder.removed, ["c-1"])
        XCTAssertEqual(recorder.deletedTokens, ["c-1"])
        XCTAssertTrue(recorder.verified.isEmpty)
    }

    func testARejectedTokenRemovesTheConnectionAndTheTokenAndHidesTheToken() async {
        let recorder = Recorder()
        recorder.verifyError = Boom(text: "401 invalid token sk-abc123-secret-value rejected")
        let outcome = await makeConnector(recorder).connect(
            serverUrl: "https://mcp.example.com/mcp", friendlyName: "Example", description: nil, token: "sk-abc123-secret-value"
        )
        guard case .failed(let message) = outcome else { return XCTFail("expected failure") }
        XCTAssertTrue(message.contains("did not accept the token"))
        XCTAssertFalse(message.contains("sk-abc123"))
        XCTAssertTrue(message.contains("[token]"))
        XCTAssertEqual(recorder.removed, ["c-1"])
        XCTAssertEqual(recorder.deletedTokens, ["c-1"])
    }

    func testScrubbingAlsoHidesLongLeadingFragmentsOfTheToken() {
        let token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        let echoed = "bad credentials for ghp_ABCDEFGHIJKLMNOPQRSTUVWX"
        let scrubbed = ConnectionTokenConnector.scrubbed(echoed, token: token)
        XCTAssertFalse(scrubbed.contains("ghp_ABCDEFGH"))
    }

    // MARK: Request parsing and replies

    func testAValidRequestIsParsedAndAMissingNameFallsBackToTheHost() {
        let request = ConnectionSecretRequest.parse([
            "request_id": "r1", "server_url": "https://mcp.example.com/mcp", "friendly_name": "  ", "description": ""
        ])
        XCTAssertEqual(request, ConnectionSecretRequest(requestId: "r1", serverUrl: "https://mcp.example.com/mcp", friendlyName: "mcp.example.com", description: nil, existingNames: [], alreadyConnectedAs: nil))
    }

    func testExistingNamesAndTheAlreadyConnectedNoticeAreParsed() throws {
        let request = try XCTUnwrap(ConnectionSecretRequest.parse([
            "request_id": "r1", "server_url": "https://huggingface.co/mcp", "friendly_name": "Hugging Face (work)",
            "existing_names": ["Hugging Face", 7, "Linear"], "already_connected_as": "Hugging Face"
        ]))
        XCTAssertEqual(request.existingNames, ["Hugging Face", "Linear"])
        XCTAssertEqual(request.alreadyConnectedAs, "Hugging Face")
    }

    func testUnsafeOrIncompleteRequestsAreRejected() {
        let bad: [[String: Any]] = [
            [:],
            ["request_id": "", "server_url": "https://a.example.com/"],
            ["request_id": "r", "server_url": "http://a.example.com/"],
            ["request_id": "r", "server_url": "https://user:pw@a.example.com/"],
            ["request_id": "r", "server_url": "not a url"],
            ["request_id": "r", "server_url": "ftp://a.example.com/"],
            ["request_id": "r"],
            ["server_url": "https://a.example.com/"]
        ]
        for json in bad {
            XCTAssertNil(ConnectionSecretRequest.parse(json), "\(json)")
        }
    }

    private func reply(_ outcome: ConnectionTokenConnector.Outcome?, lastFailure: String? = nil) throws -> [String: Any] {
        let text = try XCTUnwrap(WebSocketService_ConnectionSecret.resultMessage(requestId: "r1", outcome: outcome, lastFailureMessage: lastFailure))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
    }

    func testConnectedReplyCarriesIdAndToolCountOnly() throws {
        let json = try reply(.connected(connectionId: "c-1", toolCount: 3, friendlyName: "Example (work)", description: "Work account"))
        XCTAssertEqual(json["type"] as? String, "connection_secret_result")
        XCTAssertEqual(json["request_id"] as? String, "r1")
        XCTAssertEqual(json["status"] as? String, "connected")
        XCTAssertEqual(json["connection_id"] as? String, "c-1")
        XCTAssertEqual(json["tool_count"] as? Int, 3)
        XCTAssertEqual(json["friendly_name"] as? String, "Example (work)")
        XCTAssertEqual(json["description"] as? String, "Work account")
        XCTAssertEqual(Set(json.keys), ["type", "request_id", "status", "connection_id", "tool_count", "friendly_name", "description"])
    }

    func testClosingTheWindowIsCanceledUnlessAnAttemptAlreadyFailed() throws {
        XCTAssertEqual(try reply(nil)["status"] as? String, "canceled")
        let failed = try reply(nil, lastFailure: "Example did not accept the token")
        XCTAssertEqual(failed["status"] as? String, "failed")
        XCTAssertEqual(failed["message"] as? String, "Example did not accept the token")
    }
}
