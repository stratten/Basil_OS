import XCTest
@testable import BasilClient

final class ActivityCaptureStartupSettingsTests: XCTestCase {
    func testStartupPreferenceDecodesFromSettingsResponse() throws {
        let data = Data(
            """
            {
              "enabled": true,
              "start_at_startup": true,
              "frequency_minutes": 5.0,
              "processing_model": "local-model",
              "processing_mode": "scheduled",
              "scheduled_processing_time": "01:00",
              "processing_max_records": 0,
              "max_file_age_days": 30,
              "max_storage_mb": 500,
              "auto_cleanup_enabled": true,
              "excluded_bundle_ids": []
            }
            """.utf8
        )

        let settings = try JSONDecoder().decode(ActivityCaptureSettingsData.self, from: data)

        XCTAssertTrue(settings.activityCaptureEnabled)
        XCTAssertTrue(settings.startAtStartup)
    }

    func testStartupPreferenceUsesSnakeCaseOnPartialUpdate() throws {
        let data = try JSONEncoder().encode(
            ActivityCaptureSettingsUpdate(startAtStartup: true)
        )
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Bool]

        XCTAssertEqual(object, ["start_at_startup": true])
    }
}
