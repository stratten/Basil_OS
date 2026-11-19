import XCTest
@testable import BasilClient

final class LocalServerIntentParsingTests: XCTestCase {
    private func companionBody() -> [String: Any] {
        [
            "command": "/usr/local/bin/bridge",
            "args": ["--port", "{port}"],
            "env": ["MODE": "local"],
            "secretEnv": ["BRIDGE_TOKEN"],
            "startWithBasil": false,
            "fixedPort": 8080,
        ]
    }

    private func registrationBody(companion: Any? = nil) -> [String: Any] {
        var body: [String: Any] = [
            "friendlyName": "WhatsApp",
            "description": "  ",
            "command": "/usr/local/bin/uv",
            "args": ["run", "main.py"],
            "cwd": "/Users/me/whatsapp-mcp",
            "env": ["LOG": "info"],
            "secretEnv": ["BRIDGE_TOKEN", "API_KEY"],
            "sourceUrl": "https://github.com/example/whatsapp-mcp",
        ]
        if let companion {
            body["companion"] = companion
        }
        return body
    }

    func testParsesARegistrationWithABackgroundProgram() throws {
        let body: [String: Any] = [
            "requestId": "r-1",
            "registration": registrationBody(companion: companionBody()),
            "secretValues": ["BRIDGE_TOKEN": "t-1", "API_KEY": "k-1"],
        ]

        let intent = try XCTUnwrap(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))

        guard case .register(let requestId, let registration, let secretValues) = intent else {
            return XCTFail("Expected a register intent, got \(intent)")
        }
        XCTAssertEqual(requestId, "r-1")
        XCTAssertEqual(registration.friendlyName, "WhatsApp")
        XCTAssertNil(registration.description, "A blank description is treated as absent")
        XCTAssertEqual(registration.command, "/usr/local/bin/uv")
        XCTAssertEqual(registration.args, ["run", "main.py"])
        XCTAssertEqual(registration.cwd, "/Users/me/whatsapp-mcp")
        XCTAssertEqual(registration.env, ["LOG": "info"])
        XCTAssertEqual(registration.secretEnv, ["BRIDGE_TOKEN", "API_KEY"])
        XCTAssertEqual(registration.sourceUrl, "https://github.com/example/whatsapp-mcp")
        XCTAssertNil(registration.connectionId)
        XCTAssertEqual(registration.companion?.command, "/usr/local/bin/bridge")
        XCTAssertEqual(registration.companion?.args, ["--port", "{port}"])
        XCTAssertEqual(registration.companion?.secretEnv, ["BRIDGE_TOKEN"])
        XCTAssertEqual(registration.companion?.startWithBasil, false)
        XCTAssertEqual(registration.companion?.fixedPort, 8080)
        XCTAssertNil(registration.companion?.cwd)
        XCTAssertEqual(secretValues, ["BRIDGE_TOKEN": "t-1", "API_KEY": "k-1"])
    }

    func testARegistrationWithoutACompanionHasNone() throws {
        let body: [String: Any] = ["requestId": "r-2", "registration": registrationBody(), "secretValues": [String: String]()]
        let intent = try XCTUnwrap(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
        guard case .register(_, let registration, _) = intent else { return XCTFail("Expected a register intent") }
        XCTAssertNil(registration.companion)
    }

    func testANullCompanionMeansNone() throws {
        let body: [String: Any] = ["requestId": "r-3", "registration": registrationBody(companion: NSNull()), "secretValues": [String: String]()]
        let intent = try XCTUnwrap(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
        guard case .register(_, let registration, _) = intent else { return XCTFail("Expected a register intent") }
        XCTAssertNil(registration.companion)
    }

    func testACompanionThatIsNotAnObjectIsMalformed() {
        let body: [String: Any] = ["requestId": "r-4", "registration": registrationBody(companion: "nope"), "secretValues": [String: String]()]
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
    }

    func testACompanionMissingItsCommandIsMalformed() {
        var companion = companionBody()
        companion.removeValue(forKey: "command")
        let body: [String: Any] = ["requestId": "r-5", "registration": registrationBody(companion: companion), "secretValues": [String: String]()]
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
    }

    func testARegistrationMissingItsCommandIsMalformed() {
        var registration = registrationBody()
        registration.removeValue(forKey: "command")
        let body: [String: Any] = ["requestId": "r-6", "registration": registration, "secretValues": [String: String]()]
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
    }

    func testSecretValuesThatAreNotStringsAreMalformed() {
        let body: [String: Any] = ["requestId": "r-7", "registration": registrationBody(), "secretValues": ["API_KEY": 12345]]
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
    }

    func testAMessageWithoutARequestIdIsMalformed() {
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestStartCompanion", body: ["connectionId": "c-1"]))
    }

    func testParsesTheStartStopToggleAndSaveIntents() {
        XCTAssertEqual(
            LocalServerIntentParsing.intent(type: "requestStartCompanion", body: ["requestId": "a", "connectionId": "c-1"]),
            .startCompanion(requestId: "a", connectionId: "c-1")
        )
        XCTAssertEqual(
            LocalServerIntentParsing.intent(type: "requestStopCompanion", body: ["requestId": "b", "connectionId": "c-1"]),
            .stopCompanion(requestId: "b", connectionId: "c-1")
        )
        XCTAssertEqual(
            LocalServerIntentParsing.intent(type: "requestSetCompanionStartWithBasil", body: ["requestId": "c", "connectionId": "c-1", "startWithBasil": false]),
            .setStartWithBasil(requestId: "c", connectionId: "c-1", enabled: false)
        )
        XCTAssertEqual(
            LocalServerIntentParsing.intent(type: "requestSaveLocalServerSecrets", body: ["requestId": "d", "connectionId": "c-1", "secretValues": ["API_KEY": "k-2"]]),
            .saveSecrets(requestId: "d", connectionId: "c-1", secretValues: ["API_KEY": "k-2"])
        )
    }

    func testTheToggleNeedsABoolean() {
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestSetCompanionStartWithBasil", body: ["requestId": "c", "connectionId": "c-1"]))
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestSetCompanionStartWithBasil", body: ["requestId": "c", "connectionId": "c-1", "startWithBasil": "yes"]))
    }

    func testAnUnknownTypeIsNotAnIntent() {
        XCTAssertNil(LocalServerIntentParsing.intent(type: "requestDeleteConnection", body: ["requestId": "x", "connectionId": "c-1"]))
    }

    func testTheMessageTypesAreExactlyTheNineLocalServerRequests() {
        XCTAssertEqual(
            LocalServerIntentParsing.messageTypes,
            [
                "requestRegisterLocalServer", "requestStartCompanion", "requestStopCompanion", "requestSetCompanionStartWithBasil", "requestSaveLocalServerSecrets",
                "requestRefreshLocalServerStatus", "requestPrepareLocalServer", "requestCancelPrepareLocalServer", "requestInstallLocalServerRequirement",
            ]
        )
    }

    func testADescriptionNeverContainsASecretValue() throws {
        let body: [String: Any] = [
            "requestId": "r-8",
            "registration": registrationBody(),
            "secretValues": ["API_KEY": "super-secret-value"],
        ]
        let register = try XCTUnwrap(LocalServerIntentParsing.intent(type: "requestRegisterLocalServer", body: body))
        let save = LocalServerIntent.saveSecrets(requestId: "r-9", connectionId: "c-1", secretValues: ["API_KEY": "super-secret-value"])

        for intent in [register, save] {
            XCTAssertFalse(intent.description.contains("super-secret-value"))
            XCTAssertTrue(intent.description.contains("API_KEY"))
        }
    }
}
