import XCTest
@testable import BasilClient

final class LocalServerRecipeSupportTests: XCTestCase {
    private let install: [String: Any] = [
        "requirements": [["name": "Go", "reason": "Builds it.", "check": ["go", "version"], "install": ["brew", "install", "go"], "for_method": "build"]],
        "artifacts": [["name": "Bridge", "expects": "bin/bridge", "methods": [["kind": "download", "url": "https://example.test/bridge", "sha256": String(repeating: "a", count: 64)]]]],
    ]
    private let probe: [String: Any] = ["url": "http://127.0.0.1:{port}/status", "auth": "none", "state_path": "state", "states": ["ok": "ready"], "timeout": 5, "verbose": true]

    private func registrationBody(install: Any? = nil, probe: Any? = nil) -> [String: Any] {
        var companion: [String: Any] = ["command": "{install_dir}/bin/bridge", "args": ["{port}"], "env": [String: String](), "secretEnv": [String](), "startWithBasil": true]
        if let probe { companion["probe"] = probe }
        var body: [String: Any] = ["friendlyName": "Bridge", "command": "/usr/bin/env", "args": [String](), "env": [String: String](), "secretEnv": [String](), "companion": companion]
        if let install { body["install"] = install }
        return body
    }

    private func decode(_ json: String) throws -> APIClient.MCPConnection {
        let text = """
        {"id": "c-1", "friendly_name": "Bridge", "description": null, "server_url": "basil-stdio://c-1", "enabled": true, "registered_at": "2026-11-17T12:00:00",
         "last_tool_refresh_at": null, "last_connection_check_at": null, "last_connection_status": null, "last_connection_status_message": null,
         "server_name": null, "server_instructions": null, "auth_kind": "local", \(json) "tools": []}
        """
        return try JSONDecoder().decode(APIClient.MCPConnection.self, from: Data(text.utf8))
    }

    func testARegistrationCarriesAPastedRecipeAndProbeThroughUntouched() throws {
        let registration = try XCTUnwrap(LocalServerIntentParsing.registration(from: registrationBody(install: install, probe: probe)))
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(registration)) as? [String: Any]

        let sentInstall = try XCTUnwrap(encoded?["install"] as? [String: Any])
        let artifacts = try XCTUnwrap(sentInstall["artifacts"] as? [[String: Any]])
        let methods = try XCTUnwrap(artifacts[0]["methods"] as? [[String: Any]])
        XCTAssertEqual(methods[0]["url"] as? String, "https://example.test/bridge")
        XCTAssertEqual(methods[0]["sha256"] as? String, String(repeating: "a", count: 64))
        let sentProbe = try XCTUnwrap((encoded?["companion"] as? [String: Any])?["probe"] as? [String: Any])
        XCTAssertEqual(sentProbe["url"] as? String, "http://127.0.0.1:{port}/status")
        XCTAssertEqual(sentProbe["timeout"] as? Int, 5)
        XCTAssertEqual(sentProbe["verbose"] as? Bool, true)
        XCTAssertEqual((sentProbe["states"] as? [String: String])?["ok"], "ready")
    }

    func testARegistrationWithoutARecipeSendsNeitherKey() throws {
        let registration = try XCTUnwrap(LocalServerIntentParsing.registration(from: registrationBody()))
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(registration)) as? [String: Any]

        XCTAssertNil(registration.install)
        XCTAssertNil(registration.companion?.probe)
        XCTAssertNil(encoded?["install"])
        XCTAssertNil((encoded?["companion"] as? [String: Any])?["probe"])
    }

    func testARecipeThatIsNotAnObjectMakesTheWholeRegistrationMalformed() {
        XCTAssertNil(LocalServerIntentParsing.registration(from: registrationBody(install: ["not", "an", "object"])))
        XCTAssertNil(LocalServerIntentParsing.registration(from: registrationBody(probe: "text")))
        XCTAssertNotNil(LocalServerIntentParsing.registration(from: registrationBody(install: NSNull(), probe: NSNull())))
    }

    func testTheFourSetupIntentsParseAndRequireTheirFields() throws {
        XCTAssertEqual(LocalServerIntentParsing.intent(type: "requestRefreshLocalServerStatus", body: ["requestId": "r", "connectionId": "c"]), .refreshStatus(requestId: "r", connectionId: "c"))
        XCTAssertEqual(LocalServerIntentParsing.intent(type: "requestPrepareLocalServer", body: ["requestId": "r", "connectionId": "c"]), .prepare(requestId: "r", connectionId: "c"))
        XCTAssertEqual(LocalServerIntentParsing.intent(type: "requestCancelPrepareLocalServer", body: ["requestId": "r", "connectionId": "c"]), .cancelPrepare(requestId: "r", connectionId: "c"))
        XCTAssertEqual(
            LocalServerIntentParsing.intent(type: "requestInstallLocalServerRequirement", body: ["requestId": "r", "connectionId": "c", "name": "Go", "command": "brew install go"]),
            .installRequirement(requestId: "r", connectionId: "c", name: "Go", command: "brew install go")
        )
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestInstallLocalServerRequirement", body: ["requestId": "r", "connectionId": "c", "name": "Go"]))
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestPrepareLocalServer", body: ["requestId": "r"]))
        for type in ["requestRefreshLocalServerStatus", "requestPrepareLocalServer", "requestCancelPrepareLocalServer", "requestInstallLocalServerRequirement"] {
            XCTAssertTrue(LocalServerIntentParsing.messageTypes.contains(type), type)
        }
    }

    func testTheDescriptionOfAnInstallIntentNamesTheCommandAndNoSecret() {
        let text = LocalServerIntent.installRequirement(requestId: "r", connectionId: "c", name: "Go", command: "brew install go").description

        XCTAssertTrue(text.contains("brew install go"))
    }

    func testDecodesTheSetupRecipeAndTheLinkStateFromTheBackend() throws {
        let connection = try decode("""
        "local_server": {
          "command_summary": "uv run main.py", "source_url": null, "secret_env": [],
          "companion": {"command_summary": "bridge", "start_with_basil": true, "fixed_port": null, "secret_env": [], "status": "running", "port": 1, "last_error": null, "log_tail": "", "restart_count": 0,
                        "has_probe": true, "health_phase": "needs_action", "health_message": "Scan the code.", "action_kind": "qr", "action_value": "2@abc", "action_expires_at": "2026-11-17T12:01:00+00:00"},
          "install": {"phase": "needs_requirement", "message": "Go is missing.", "ready": false, "active": false, "artifact": "Bridge", "requirement": "Go", "can_install": true, "detail": null,
                      "requirements": [{"name": "Go", "reason": "Builds it.", "for_method": "build", "install_command": "brew install go"}],
                      "artifacts": [{"name": "Bridge", "expects": "bin/bridge", "ready": false, "sources": ["Download https://example.test/bridge (SHA-256 aaaa)"]}]}
        },
        """)

        let details = try XCTUnwrap(connection.localServer)
        let companion = try XCTUnwrap(details.companion)
        XCTAssertEqual(companion.hasProbe, true)
        XCTAssertEqual(companion.healthPhase, "needs_action")
        XCTAssertEqual(companion.actionKind, "qr")
        XCTAssertEqual(companion.actionValue, "2@abc")
        let install = try XCTUnwrap(details.install)
        XCTAssertEqual(install.phase, "needs_requirement")
        XCTAssertTrue(install.canInstall)
        XCTAssertEqual(install.requirements.first?.installCommand, "brew install go")
        XCTAssertEqual(install.artifacts.first?.sources, ["Download https://example.test/bridge (SHA-256 aaaa)"])
    }

    func testAnOlderBackendWithNoSetupOrLinkFieldsStillDecodes() throws {
        let connection = try decode("""
        "local_server": {"command_summary": "uv run main.py", "source_url": null, "secret_env": [],
          "companion": {"command_summary": "bridge", "start_with_basil": true, "fixed_port": null, "secret_env": [], "status": "stopped", "port": null, "last_error": null, "log_tail": "", "restart_count": 0}},
        """)

        let details = try XCTUnwrap(connection.localServer)
        XCTAssertNil(details.install)
        XCTAssertNil(details.companion?.hasProbe)
        XCTAssertNil(details.companion?.healthPhase)
    }

    func testThePayloadCarriesTheSetupAndTheLinkWithTheCodeButNoOtherSecret() throws {
        let connection = try decode("""
        "local_server": {
          "command_summary": "uv run main.py", "source_url": null, "secret_env": [],
          "companion": {"command_summary": "bridge", "start_with_basil": true, "fixed_port": null, "secret_env": [], "status": "running", "port": 1, "last_error": null, "log_tail": "", "restart_count": 0,
                        "has_probe": true, "health_phase": "needs_action", "health_message": "Scan the code.", "action_kind": "qr", "action_value": "2@abc", "action_expires_at": null},
          "install": {"phase": "ready", "message": "", "ready": true, "active": false, "artifact": null, "requirement": null, "can_install": false, "detail": null,
                      "requirements": [{"name": "Go", "reason": "Builds it.", "for_method": "build", "install_command": null}],
                      "artifacts": [{"name": "Bridge", "expects": "bin/bridge", "ready": true, "sources": []}]}
        },
        """)

        let payload = try XCTUnwrap(LocalServerPayload.payload(for: connection.localServer, connectionId: "c-1", isSecretSaved: { _ in true }))
        let companion = try XCTUnwrap(payload["companion"] as? [String: Any])
        XCTAssertEqual(companion["hasProbe"] as? Bool, true)
        let health = try XCTUnwrap(companion["health"] as? [String: Any])
        XCTAssertEqual(health["phase"] as? String, "needs_action")
        XCTAssertEqual(health["actionKind"] as? String, "qr")
        XCTAssertEqual(health["actionValue"] as? String, "2@abc")
        let installPayload = try XCTUnwrap(payload["install"] as? [String: Any])
        XCTAssertEqual(installPayload["ready"] as? Bool, true)
        XCTAssertEqual(installPayload["canInstall"] as? Bool, false)
        let requirements = try XCTUnwrap(installPayload["requirements"] as? [[String: Any]])
        XCTAssertEqual(requirements[0]["forMethod"] as? String, "build")
        let artifacts = try XCTUnwrap(installPayload["artifacts"] as? [[String: Any]])
        XCTAssertEqual(artifacts[0]["expects"] as? String, "bin/bridge")
    }

    func testAServerWithoutARecipeOrProbeHasNoInstallAndNoHealth() throws {
        let connection = try decode("""
        "local_server": {"command_summary": "uv run main.py", "source_url": null, "secret_env": [],
          "companion": {"command_summary": "bridge", "start_with_basil": true, "fixed_port": null, "secret_env": [], "status": "running", "port": 1, "last_error": null, "log_tail": "", "restart_count": 0}},
        """)

        let payload = try XCTUnwrap(LocalServerPayload.payload(for: connection.localServer, connectionId: "c-1", isSecretSaved: { _ in true }))
        let companion = try XCTUnwrap(payload["companion"] as? [String: Any])

        XCTAssertEqual(companion["hasProbe"] as? Bool, false)
        XCTAssertNil(companion["health"])
        XCTAssertNil(payload["install"] as? [String: Any])
    }

    func testJSONValueRoundTripsIntegersBooleansNullsAndNesting() throws {
        let original: [String: Any] = ["a": 1, "b": 2.5, "c": true, "d": NSNull(), "e": ["x", "y"], "f": ["g": ["h": 7]]]
        let value = try XCTUnwrap(LocalServerJSONValue(any: original))
        let data = try JSONEncoder().encode(value)
        let decoded = try JSONDecoder().decode(LocalServerJSONValue.self, from: data)

        XCTAssertEqual(decoded, value)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["a"] as? Int, 1)
        XCTAssertEqual(object["b"] as? Double, 2.5)
        XCTAssertEqual(object["c"] as? Bool, true)
        XCTAssertTrue(object["d"] is NSNull)
        XCTAssertEqual(((object["f"] as? [String: Any])?["g"] as? [String: Any])?["h"] as? Int, 7)
        XCTAssertNil(LocalServerJSONValue(any: Date()))
    }
}
