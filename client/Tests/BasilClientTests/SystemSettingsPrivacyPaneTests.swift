import XCTest
@testable import BasilClient

final class SystemSettingsPrivacyPaneTests: XCTestCase {
    private let prefix = "x-apple.systempreferences:com.apple.preference.security?"

    func testEveryPaneHasTheExactAnchorUrlTheAppUsedBefore() {
        XCTAssertEqual(SystemSettingsPrivacyPane.general.url.absoluteString, prefix + "Privacy")
        XCTAssertEqual(SystemSettingsPrivacyPane.microphone.url.absoluteString, prefix + "Privacy_Microphone")
        XCTAssertEqual(SystemSettingsPrivacyPane.accessibility.url.absoluteString, prefix + "Privacy_Accessibility")
        XCTAssertEqual(SystemSettingsPrivacyPane.inputMonitoring.url.absoluteString, prefix + "Privacy_ListenEvent")
        XCTAssertEqual(SystemSettingsPrivacyPane.appleEvents.url.absoluteString, prefix + "Privacy_Automation")
        XCTAssertEqual(SystemSettingsPrivacyPane.screenRecording.url.absoluteString, prefix + "Privacy_ScreenCapture")
    }

    func testEveryCaseBuildsAValidUrl() {
        for pane in SystemSettingsPrivacyPane.allCases {
            XCTAssertEqual(pane.url.scheme, "x-apple.systempreferences", "\(pane)")
            XCTAssertTrue(pane.url.absoluteString.hasSuffix(pane.rawValue), "\(pane)")
        }
    }

    func testPermissionKindsMapToTheirPanes() {
        XCTAssertEqual(SystemSettingsPrivacyPane(permissionKind: "microphone"), .microphone)
        XCTAssertEqual(SystemSettingsPrivacyPane(permissionKind: "accessibility"), .accessibility)
        XCTAssertEqual(SystemSettingsPrivacyPane(permissionKind: "input_monitoring"), .inputMonitoring)
        XCTAssertEqual(SystemSettingsPrivacyPane(permissionKind: "apple_events"), .appleEvents)
        XCTAssertEqual(SystemSettingsPrivacyPane(permissionKind: "screen_recording"), .screenRecording)
    }

    func testUnknownEmptyAndWrongCaseKindsReturnNil() {
        XCTAssertNil(SystemSettingsPrivacyPane(permissionKind: ""))
        XCTAssertNil(SystemSettingsPrivacyPane(permissionKind: "Microphone"))
        XCTAssertNil(SystemSettingsPrivacyPane(permissionKind: "privacy"))
        XCTAssertNil(SystemSettingsPrivacyPane(permissionKind: "general"))
        XCTAssertNil(SystemSettingsPrivacyPane(permissionKind: "camera"))
    }

    func testBridgeOpenPolicyStillRefusesTheSchemeFromWebContent() {
        for pane in SystemSettingsPrivacyPane.allCases {
            XCTAssertEqual(BridgeOpenPolicy.externalURLAction(for: pane.url), .refuse, "\(pane)")
        }
    }
}
