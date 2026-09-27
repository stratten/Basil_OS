import XCTest

final class SettingsSwiftUICutoverTests: XCTestCase {
    private var clientRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func source(_ relativePath: String) throws -> String {
        try String(
            contentsOf: clientRoot.appendingPathComponent("Sources/\(relativePath)"),
            encoding: .utf8
        )
    }

    func testSettingsEntryPointsOpenReactSettingsShell() throws {
        let applicationMenu = try source("App/AppDelegate/AppDelegate_MenuBar.swift")
        let statusBarManager = try source("Services/StatusBar/StatusBarManager.swift")
        let statusBarMenu = try source("Services/StatusBar/StatusBarMenuBuilder.swift")

        XCTAssertTrue(applicationMenu.contains("SettingsShellWindowController.shared.show()"))
        XCTAssertTrue(statusBarManager.contains("func openNewSettings()"))
        XCTAssertTrue(statusBarManager.contains("SettingsShellWindowController.shared.show()"))
        XCTAssertFalse(statusBarManager.contains("openSettingsReact"))
        XCTAssertFalse(statusBarMenu.contains("Settings - React"))
    }

    func testActiveSourcesContainNoLegacySettingsEntryPoint() throws {
        let applicationDelegate = try source("App/AppDelegate/AppDelegate.swift")
        let windows = try source("App/AppDelegate/AppDelegate_Windows.swift")
        let aestheticSystem = try source("Support/AestheticSystem.swift")
        let activityCaptureViewModel = try source("Settings/ActivityCaptureSettings/ActivityCaptureSettingsViewModel.swift")

        XCTAssertFalse(applicationDelegate.contains("settingsWindow"))
        XCTAssertFalse(applicationDelegate.contains("newSettingsWindow"))
        XCTAssertFalse(windows.contains("showNewSettings"))
        XCTAssertFalse(windows.contains("NewSettingsView"))
        XCTAssertFalse(aestheticSystem.contains("navigateToTranscriptionHistory"))
        XCTAssertFalse(activityCaptureViewModel.contains("SettingsWindowClosing"))
    }
}
