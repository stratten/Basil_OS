import XCTest
@testable import BasilClient

@MainActor
final class ConnectionsSettingsPayloadTests: XCTestCase {
    func testValidateExternalUrlAcceptsHttps() {
        XCTAssertNil(SettingsShellWindowController.validateExternalUrl("https://github.com/login/device"))
    }

    func testValidateExternalUrlRejectsHttp() {
        XCTAssertNotNil(SettingsShellWindowController.validateExternalUrl("http://github.com/login/device"))
    }

    func testValidateExternalUrlRejectsMalformedUrl() {
        XCTAssertNotNil(SettingsShellWindowController.validateExternalUrl("not a url"))
    }

    func testValidateExternalUrlRejectsCustomScheme() {
        XCTAssertNotNil(SettingsShellWindowController.validateExternalUrl("basil://mcp/connection_complete"))
    }

    func testIsBlankOrWhitespaceDetectsEmptyString() {
        XCTAssertTrue(SettingsShellWindowController.isBlankOrWhitespace(""))
    }

    func testIsBlankOrWhitespaceDetectsWhitespaceOnly() {
        XCTAssertTrue(SettingsShellWindowController.isBlankOrWhitespace("   \n\t "))
    }

    func testIsBlankOrWhitespaceAcceptsNonEmptyValue() {
        XCTAssertFalse(SettingsShellWindowController.isBlankOrWhitespace("GitHub"))
    }

    func testIsBlankOrWhitespaceAcceptsValueWithSurroundingWhitespace() {
        XCTAssertFalse(SettingsShellWindowController.isBlankOrWhitespace("  GitHub  "))
    }

    func testValidateProviderProfileFieldsRejectsBlankDisplayName() {
        XCTAssertNotNil(SettingsShellWindowController.validateProviderProfileFields(displayName: "  ", launchArgv: ["/usr/local/bin/codex"]))
    }

    func testValidateProviderProfileFieldsRejectsEmptyLaunchArgv() {
        XCTAssertNotNil(SettingsShellWindowController.validateProviderProfileFields(displayName: "Codex CLI", launchArgv: []))
    }

    func testValidateProviderProfileFieldsRejectsBlankExecutablePath() {
        XCTAssertNotNil(SettingsShellWindowController.validateProviderProfileFields(displayName: "Codex CLI", launchArgv: ["   "]))
    }

    func testValidateProviderProfileFieldsAcceptsValidInput() {
        XCTAssertNil(SettingsShellWindowController.validateProviderProfileFields(displayName: "Codex CLI", launchArgv: ["/usr/local/bin/codex", "--acp"]))
    }

    func testValidateWorkspaceGrantFieldsRejectsBlankLabel() {
        XCTAssertNotNil(SettingsShellWindowController.validateWorkspaceGrantFields(workspaceLabel: ""))
    }

    func testValidateWorkspaceGrantFieldsAcceptsNonBlankLabel() {
        XCTAssertNil(SettingsShellWindowController.validateWorkspaceGrantFields(workspaceLabel: "My Project"))
    }
}
