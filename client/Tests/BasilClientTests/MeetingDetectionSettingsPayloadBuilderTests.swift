import XCTest
@testable import BasilClient

@MainActor
final class MeetingDetectionSettingsPayloadBuilderTests: XCTestCase {
    func testMapsSettingsFieldsToCamelCaseKeys() {
        let viewModel = MeetingDetectionSettingsViewModel()
        viewModel.enabled = true
        viewModel.mode = "auto_start"
        viewModel.pollSeconds = 15
        viewModel.excludedBundleIds = ["com.stratten.basil", "com.apple.FaceTime"]
        viewModel.excludedAppNamesText = "Discord\nSlack"
        viewModel.cooldownMinutes = 30
        viewModel.useCalendarEnrichment = true
        viewModel.requireCalendarMatch = false
        viewModel.autoEnd = true
        viewModel.inactivityTimeoutMinutes = 3

        let payload = MeetingDetectionSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel)

        XCTAssertEqual(payload["enabled"] as? Bool, true)
        XCTAssertEqual(payload["mode"] as? String, "auto_start")
        XCTAssertEqual(payload["pollSeconds"] as? Double, 15)
        XCTAssertEqual(payload["excludedBundleIds"] as? [String], ["com.stratten.basil", "com.apple.FaceTime"])
        XCTAssertEqual(payload["excludedAppNames"] as? [String], ["Discord", "Slack"])
        XCTAssertEqual(payload["cooldownMinutes"] as? Double, 30)
        XCTAssertEqual(payload["useCalendarEnrichment"] as? Bool, true)
        XCTAssertEqual(payload["requireCalendarMatch"] as? Bool, false)
        XCTAssertEqual(payload["autoEnd"] as? Bool, true)
        XCTAssertEqual(payload["inactivityTimeoutMinutes"] as? Double, 3)
    }

    func testExcludedAppsPayloadResolvesOneEntryPerExcludedBundleId() {
        let viewModel = MeetingDetectionSettingsViewModel()
        viewModel.excludedBundleIds = ["com.stratten.basil"]

        let payload = MeetingDetectionSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel)

        XCTAssertEqual(payload.count, 1)
        XCTAssertEqual(payload.first?["bundleId"] as? String, "com.stratten.basil")
        XCTAssertNotNil(payload.first?["name"] as? String)
    }

    func testAppSearchResultsPayloadIsEmptyForAnEmptyQuery() {
        let payload = MeetingDetectionSettingsPayloadBuilder.makeAppSearchResultsPayload(query: "   ")
        XCTAssertTrue(payload.isEmpty)
    }

    func testRequiredBundleIdsIsNonEmptyAndStable() {
        let first = MeetingDetectionSettingsPayloadBuilder.requiredBundleIds
        let second = MeetingDetectionSettingsPayloadBuilder.requiredBundleIds
        XCTAssertFalse(first.isEmpty)
        XCTAssertEqual(first, second)
    }
}
