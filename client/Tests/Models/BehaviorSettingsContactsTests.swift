import XCTest
@testable import BasilClient

final class BehaviorSettingsContactsTests: XCTestCase {
    func testBehaviorSettingsDefaultsMacContactsPreferenceWhenMissing() throws {
        let json = """
        {
          "start_on_startup": false,
          "show_notifications": true,
          "minimize_to_tray": true,
          "hold_enabled": false,
          "hold_duration": 0.5,
          "enable_monitoring_at_startup": true,
          "enable_voice_listener_at_startup": false
        }
        """.data(using: .utf8)!

        let settings = try JSONDecoder().decode(BehaviorSettings.self, from: json)

        XCTAssertFalse(settings.allowMacContactsForGeneration)
        XCTAssertFalse(settings.enableVoiceListenerAtStartup)
    }

    func testBehaviorSettingsEncodesMacContactsPreference() throws {
        let settings = BehaviorSettings(
            startOnStartup: false,
            showNotifications: true,
            minimizeToTray: true,
            holdEnabled: false,
            holdDuration: 0.5,
            enableMonitoringAtStartup: true,
            allowMacContactsForGeneration: true
        )

        let data = try JSONEncoder().encode(settings)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(object?["allow_mac_contacts_for_generation"] as? Bool, true)
    }

    func testMacContactsStatusResponseDecodesSnakeCasePayload() throws {
        let json = """
        {
          "available": true,
          "preference_enabled": true,
          "authorization_status": "authorized",
          "can_lookup": true,
          "detail": null
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let status = try decoder.decode(MacContactsStatusResponse.self, from: json)

        XCTAssertTrue(status.available)
        XCTAssertTrue(status.preferenceEnabled)
        XCTAssertEqual(status.authorizationStatus, "authorized")
        XCTAssertTrue(status.canLookup)
        XCTAssertNil(status.detail)
    }
}
