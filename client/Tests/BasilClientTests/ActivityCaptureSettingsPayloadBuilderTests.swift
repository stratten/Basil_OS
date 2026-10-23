import XCTest
@testable import BasilClient

@MainActor
final class ActivityCaptureSettingsPayloadBuilderTests: XCTestCase {
    func testSettingsPayloadDerivesFrequencySecondsFromMinutesWithoutDrift() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.captureFrequencyMinutes = 0.5
        let payload = ActivityCaptureSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel)
        XCTAssertEqual(payload["frequencySeconds"] as? Int, 30)

        viewModel.captureFrequencyMinutes = 5.0
        let payload2 = ActivityCaptureSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel)
        XCTAssertEqual(payload2["frequencySeconds"] as? Int, 300)
    }

    func testSettingsPayloadSplitsCleanupTimeIntoHourAndMinute() {
        let viewModel = ActivityCaptureSettingsViewModel()
        var components = DateComponents()
        components.hour = 3
        components.minute = 45
        viewModel.cleanupTime = Calendar.current.date(from: components) ?? Date()
        let payload = ActivityCaptureSettingsPayloadBuilder.makeSettingsPayload(viewModel: viewModel)
        XCTAssertEqual(payload["cleanupHour"] as? Int, 3)
        XCTAssertEqual(payload["cleanupMinute"] as? Int, 45)
    }

    func testStatsPayloadIsNilWhenViewModelHasNoStats() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.captureStats = nil
        XCTAssertNil(ActivityCaptureSettingsPayloadBuilder.makeStatsPayload(viewModel: viewModel))
    }

    func testStatsPayloadIncludesFileCounts() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.captureStats = ActivityCaptureStats(
            totalFiles: 12,
            totalSizeBytes: 4_000_000,
            filesLast7Days: 3,
            sizeLast7DaysBytes: 1_000_000,
            filesLast30Days: 10,
            sizeLast30DaysBytes: 3_500_000
        )
        let payload = ActivityCaptureSettingsPayloadBuilder.makeStatsPayload(viewModel: viewModel)
        XCTAssertEqual(payload?["totalFiles"] as? Int, 12)
        XCTAssertEqual(payload?["filesLast7Days"] as? Int, 3)
        XCTAssertEqual(payload?["filesLast30Days"] as? Int, 10)
    }

    func testStatusPayloadIncludesActivityCountsAlongsideTodaysCaptures() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.todaysCaptures = 42
        viewModel.totalCapturesLast7Days = 310
        viewModel.totalCapturesLast30Days = 648
        let payload = ActivityCaptureSettingsPayloadBuilder.makeStatusPayload(viewModel: viewModel)
        XCTAssertEqual(payload["todaysCaptures"] as? Int, 42)
        XCTAssertEqual(payload["totalCapturesLast7Days"] as? Int, 310)
        XCTAssertEqual(payload["totalCapturesLast30Days"] as? Int, 648)
    }

    func testProcessingProgressPayloadReturnsNSNullWhenNoProgressIsActive() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.processingProgress = nil
        let payload = ActivityCaptureSettingsPayloadBuilder.makeProcessingProgressPayload(viewModel: viewModel)
        XCTAssertTrue(payload is NSNull)
    }

    func testProcessingProgressPayloadIncludesCounters() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.processingProgress = ActivityProcessingProgressResponse(
            active: true, total: 10, processed: 4, succeeded: 3, failed: 1, remaining: 6,
            etaSeconds: 90, cancelRequested: false, startedAt: nil, lastError: nil,
            maxRecords: 0, analysisConcurrency: 4, processingStrategy: "api_parallel"
        )
        let payload = ActivityCaptureSettingsPayloadBuilder.makeProcessingProgressPayload(viewModel: viewModel) as? [String: Any]
        XCTAssertEqual(payload?["active"] as? Bool, true)
        XCTAssertEqual(payload?["total"] as? Int, 10)
        XCTAssertEqual(payload?["processed"] as? Int, 4)
        XCTAssertEqual(payload?["remaining"] as? Int, 6)
        XCTAssertEqual(payload?["processingStrategy"] as? String, "api_parallel")
        XCTAssertEqual(payload?["analysisConcurrency"] as? Int, 4)
    }

    func testAvailableAppsPayloadReturnsUniqueRegularAppsWithRequiredKeys() {
        let payload = ActivityCaptureSettingsPayloadBuilder.makeAvailableAppsPayload()
        var seenBundleIds = Set<String>()
        for entry in payload {
            guard let bundleId = entry["bundleId"] as? String else {
                XCTFail("Each available-app entry must have a string bundleId")
                continue
            }
            XCTAssertTrue(seenBundleIds.insert(bundleId).inserted, "bundleId \(bundleId) appeared more than once")
            XCTAssertNotNil(entry["name"] as? String)
            XCTAssertTrue(entry["iconDataUrl"] is String || entry["iconDataUrl"] is NSNull)
        }
    }

    func testAppSearchResultsPayloadIsEmptyForABlankQuery() {
        XCTAssertEqual(ActivityCaptureSettingsPayloadBuilder.makeAppSearchResultsPayload(query: "   ").count, 0)
    }

    func testAppSearchResultsPayloadFindsAnInstalledFinderMatchByName() {
        let payload = ActivityCaptureSettingsPayloadBuilder.makeAppSearchResultsPayload(query: "Finder")
        XCTAssertTrue(payload.contains { ($0["bundleId"] as? String) == "com.apple.finder" })
    }

    func testAppSearchResultsPayloadReturnsNoDuplicateBundleIds() {
        let payload = ActivityCaptureSettingsPayloadBuilder.makeAppSearchResultsPayload(query: "a")
        let bundleIds = payload.compactMap { $0["bundleId"] as? String }
        XCTAssertEqual(bundleIds.count, Set(bundleIds).count)
    }

    func testExcludedAppsPayloadResolvesNameAndIconForABundleIdThatIsNotCurrentlyRunning() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.excludedBundleIds = ["com.apple.finder"]
        let payload = ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel)
        XCTAssertEqual(payload.count, 1)
        XCTAssertEqual(payload[0]["bundleId"] as? String, "com.apple.finder")
        XCTAssertEqual(payload[0]["name"] as? String, "Finder")
    }

    func testExcludedAppsPayloadFallsBackGracefullyForAnUnknownBundleId() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.excludedBundleIds = ["com.example.doesNotExist"]
        let payload = ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel)
        XCTAssertEqual(payload.count, 1)
        XCTAssertEqual(payload[0]["bundleId"] as? String, "com.example.doesNotExist")
        XCTAssertNotNil(payload[0]["name"] as? String)
        XCTAssertTrue(payload[0]["iconDataUrl"] is NSNull)
    }

    func testExcludedAppsPayloadPreservesOrderAndCountMatchingExcludedBundleIds() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.excludedBundleIds = ["com.apple.finder", "com.apple.Terminal", "com.example.doesNotExist"]
        let payload = ActivityCaptureSettingsPayloadBuilder.makeExcludedAppsPayload(viewModel: viewModel)
        XCTAssertEqual(payload.map { $0["bundleId"] as? String }, ["com.apple.finder", "com.apple.Terminal", "com.example.doesNotExist"])
    }

    func testModelsPayloadSerializesEachOption() {
        let viewModel = ActivityCaptureSettingsViewModel()
        viewModel.availableModels = [
            ActivityCaptureModelInfo(id: "local-1", displayName: "Local Model", provider: "local", isLocal: true),
            ActivityCaptureModelInfo(id: "api-1", displayName: "API Model", provider: "openai", isLocal: false),
        ]
        let payload = ActivityCaptureSettingsPayloadBuilder.makeModelsPayload(viewModel: viewModel)
        XCTAssertEqual(payload.count, 2)
        XCTAssertEqual(payload[0]["id"] as? String, "local-1")
        XCTAssertEqual(payload[0]["isLocal"] as? Bool, true)
        XCTAssertEqual(payload[1]["provider"] as? String, "openai")
    }
}
