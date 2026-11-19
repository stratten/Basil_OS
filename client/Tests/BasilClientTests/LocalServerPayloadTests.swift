import XCTest
@testable import BasilClient

final class LocalServerPayloadTests: XCTestCase {
    private func details(companion: APIClient.LocalServerCompanionStatus?) -> APIClient.LocalServerDetails {
        APIClient.LocalServerDetails(
            commandSummary: "uv run main.py",
            sourceUrl: "https://github.com/example/whatsapp-mcp",
            secretEnv: ["API_KEY"],
            companion: companion
        )
    }

    private func companion(status: String) -> APIClient.LocalServerCompanionStatus {
        APIClient.LocalServerCompanionStatus(
            commandSummary: "/usr/local/bin/bridge --port {port}",
            startWithBasil: true,
            fixedPort: nil,
            secretEnv: ["BRIDGE_TOKEN"],
            status: status,
            port: 51234,
            lastError: nil,
            logTail: "",
            restartCount: 2
        )
    }

    func testAConnectionThatIsNotALocalServerHasNoPayload() {
        XCTAssertNil(LocalServerPayload.payload(for: nil, connectionId: "c-1", isSecretSaved: { _ in true }))
    }

    func testTheSecretFlagsComeFromTheKeychainAccountOfEachName() throws {
        var asked: [String] = []
        let payload = try XCTUnwrap(LocalServerPayload.payload(for: details(companion: nil), connectionId: "c-1") { account in
            asked.append(account)
            return true
        })

        XCTAssertEqual(asked, ["c-1.env.API_KEY"])
        let secrets = try XCTUnwrap(payload["secretEnv"] as? [[String: Any]])
        XCTAssertEqual(secrets.count, 1)
        XCTAssertEqual(secrets[0]["name"] as? String, "API_KEY")
        XCTAssertEqual(secrets[0]["saved"] as? Bool, true)
    }

    func testAMissingSecretIsReportedAsNotSaved() throws {
        let payload = try XCTUnwrap(LocalServerPayload.payload(for: details(companion: nil), connectionId: "c-1", isSecretSaved: { _ in false }))
        let secrets = try XCTUnwrap(payload["secretEnv"] as? [[String: Any]])
        XCTAssertEqual(secrets[0]["saved"] as? Bool, false)
    }

    func testTheBasicFieldsAreCarried() throws {
        let payload = try XCTUnwrap(LocalServerPayload.payload(for: details(companion: nil), connectionId: "c-1", isSecretSaved: { _ in true }))
        XCTAssertEqual(payload["commandSummary"] as? String, "uv run main.py")
        XCTAssertEqual(payload["sourceUrl"] as? String, "https://github.com/example/whatsapp-mcp")
        XCTAssertNil(payload["companion"] as? [String: Any], "A server without a background program has no companion object")
    }

    func testTheBackgroundProgramStatusAndItsSecretsAreCarried() throws {
        let payload = try XCTUnwrap(LocalServerPayload.payload(
            for: details(companion: companion(status: "running")),
            connectionId: "c-1",
            isSecretSaved: { $0 == "c-1.env.BRIDGE_TOKEN" }
        ))

        let companion = try XCTUnwrap(payload["companion"] as? [String: Any])
        XCTAssertEqual(companion["status"] as? String, "running")
        XCTAssertEqual(companion["port"] as? Int, 51234)
        XCTAssertEqual(companion["restartCount"] as? Int, 2)
        XCTAssertEqual(companion["startWithBasil"] as? Bool, true)
        XCTAssertEqual(companion["commandSummary"] as? String, "/usr/local/bin/bridge --port {port}")
        XCTAssertEqual(companion["logTail"] as? String, "")
        let secrets = try XCTUnwrap(companion["secretEnv"] as? [[String: Any]])
        XCTAssertEqual(secrets[0]["name"] as? String, "BRIDGE_TOKEN")
        XCTAssertEqual(secrets[0]["saved"] as? Bool, true)
        let serverSecrets = try XCTUnwrap(payload["secretEnv"] as? [[String: Any]])
        XCTAssertEqual(serverSecrets[0]["saved"] as? Bool, false)
    }

    func testThePayloadNeverContainsASecretValue() throws {
        let payload = try XCTUnwrap(LocalServerPayload.payload(for: details(companion: companion(status: "running")), connectionId: "c-1", isSecretSaved: { _ in true }))
        let data = try JSONSerialization.data(withJSONObject: JSONSanitizer.sanitize(payload))
        let text = String(decoding: data, as: UTF8.self)
        XCTAssertTrue(text.contains("\"saved\":true"))
        XCTAssertFalse(text.contains("super-secret"))
    }
}

/// Mirrors what the web view bridge does to optional values before serializing: a nil becomes null.
private enum JSONSanitizer {
    static func sanitize(_ value: Any) -> Any {
        if let dictionary = value as? [String: Any] {
            return dictionary.mapValues { sanitize($0) }
        }
        if let array = value as? [Any] {
            return array.map { sanitize($0) }
        }
        let mirror = Mirror(reflecting: value)
        if mirror.displayStyle == .optional {
            return mirror.children.first.map { sanitize($0.value) } ?? NSNull()
        }
        return value
    }
}
