import XCTest
@testable import BasilClient

@MainActor
final class LocalServerRegistrationValidationTests: XCTestCase {
    private func registration(
        name: String = "WhatsApp",
        command: String = "/usr/local/bin/uv",
        secretEnv: [String] = [],
        companion: APIClient.LocalServerCompanionRegistration? = nil
    ) -> APIClient.LocalServerRegistration {
        APIClient.LocalServerRegistration(
            friendlyName: name,
            description: nil,
            command: command,
            args: [],
            cwd: nil,
            env: [:],
            sourceUrl: nil,
            secretEnv: secretEnv,
            companion: companion,
            connectionId: nil
        )
    }

    private func companion(command: String = "/usr/local/bin/bridge", secretEnv: [String] = []) -> APIClient.LocalServerCompanionRegistration {
        APIClient.LocalServerCompanionRegistration(command: command, args: [], cwd: nil, env: [:], secretEnv: secretEnv, startWithBasil: true, fixedPort: nil)
    }

    func testAValidRegistrationPasses() {
        XCTAssertNil(SettingsShellWindowController.validateLocalServerRegistration(registration(), secretValues: [:]))
    }

    func testABlankNameIsRejected() {
        XCTAssertEqual(SettingsShellWindowController.validateLocalServerRegistration(registration(name: "  "), secretValues: [:]), "A name is required.")
    }

    func testABlankCommandIsRejected() {
        XCTAssertEqual(SettingsShellWindowController.validateLocalServerRegistration(registration(command: ""), secretValues: [:]), "A command is required.")
    }

    func testABlankBackgroundProgramCommandIsRejected() {
        XCTAssertEqual(
            SettingsShellWindowController.validateLocalServerRegistration(registration(companion: companion(command: " ")), secretValues: [:]),
            "The background program needs a command."
        )
    }

    func testADeclaredSecretWithoutAValueIsRejected() {
        XCTAssertEqual(
            SettingsShellWindowController.validateLocalServerRegistration(registration(secretEnv: ["API_KEY"]), secretValues: [:]),
            "A value for API_KEY is required."
        )
    }

    func testADeclaredSecretWithABlankValueIsRejected() {
        XCTAssertEqual(
            SettingsShellWindowController.validateLocalServerRegistration(registration(secretEnv: ["API_KEY"]), secretValues: ["API_KEY": "   "]),
            "A value for API_KEY is required."
        )
    }

    func testABackgroundProgramSecretWithoutAValueIsRejected() {
        XCTAssertEqual(
            SettingsShellWindowController.validateLocalServerRegistration(registration(companion: companion(secretEnv: ["BRIDGE_TOKEN"])), secretValues: [:]),
            "A value for BRIDGE_TOKEN is required."
        )
    }

    func testEveryDeclaredSecretWithAValuePasses() {
        XCTAssertNil(SettingsShellWindowController.validateLocalServerRegistration(
            registration(secretEnv: ["API_KEY"], companion: companion(secretEnv: ["BRIDGE_TOKEN"])),
            secretValues: ["API_KEY": "k-1", "BRIDGE_TOKEN": "t-1"]
        ))
    }
}
