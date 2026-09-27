import XCTest
@testable import BasilClient

final class MemoriesSettingsPayloadTests: XCTestCase {
    private let sampleSettings = ZettelSettingsData(
        enabledSources: ["agent_task", "conversation"],
        historyDays: 30,
        cardingEnabled: true,
        cardingIntervalMinutes: 15,
        limitPerSourcePerPass: 500,
        narrativeEnabled: true,
        narrativeModel: "local-model",
        narrativeMode: "scheduled",
        narrativeScheduledTime: "02:00",
        narrativeIntervalMinutes: 30,
        narrativeBatchSize: 50,
        narrativeMaxAttempts: 3,
        narrativeMaxRecords: 0
    )

    func testSettingsPayloadUsesCamelCaseKeys() {
        let payload = MemoriesSettingsPayloadBuilder.settingsPayload(sampleSettings)
        XCTAssertEqual(payload["enabledSources"] as? [String], ["agent_task", "conversation"])
        XCTAssertEqual(payload["narrativeScheduledTime"] as? String, "02:00")
        XCTAssertEqual(payload["narrativeMaxRecords"] as? Int, 0)
    }

    func testStatsPayloadNilBecomesNSNull() {
        let payload = MemoriesSettingsPayloadBuilder.statsPayload(nil)
        XCTAssertTrue(payload is NSNull)
    }

    func testStatsPayloadIncludesBySource() {
        let stats = ZettelStatsData(
            collected: 10, summarized: 4, awaitingSummary: 6, awaitingRetry: 1, failed: 0,
            awaitingCollection: 2,
            bySource: [ZettelSourceStat(kind: "agent_task", collected: 5, awaitingCollection: 1)]
        )
        let payload = MemoriesSettingsPayloadBuilder.statsPayload(stats) as? [String: Any]
        let bySource = payload?["bySource"] as? [[String: Any]]
        XCTAssertEqual(bySource?.first?["kind"] as? String, "agent_task")
    }

    func testNarrativeProgressPayloadNilBecomesNSNull() {
        let payload = MemoriesSettingsPayloadBuilder.narrativeProgressPayload(nil)
        XCTAssertTrue(payload is NSNull)
    }

    func testNarrativeProgressPayloadIncludesOptionalNulls() {
        let progress = NarrativeProgressData(
            active: true, total: 10, processed: 3, finalized: 3, stillOpen: 0, failed: 0, remaining: 7,
            etaSeconds: nil, lastError: nil, cancelling: nil, analysisConcurrency: nil, processingStrategy: nil
        )
        let payload = MemoriesSettingsPayloadBuilder.narrativeProgressPayload(progress) as? [String: Any]
        XCTAssertTrue(payload?["etaSeconds"] is NSNull)
        XCTAssertEqual(payload?["active"] as? Bool, true)
    }

    func testModelsPayloadEmptyList() {
        XCTAssertEqual(MemoriesSettingsPayloadBuilder.modelsPayload([]).count, 0)
    }

    func testModelsPayloadMapsLocalFlag() {
        let models = [ActivityCaptureModelInfo(id: "m1", displayName: "Model 1", provider: "llama", isLocal: true)]
        let payload = MemoriesSettingsPayloadBuilder.modelsPayload(models)
        XCTAssertEqual(payload.first?["isLocal"] as? Bool, true)
        XCTAssertEqual(payload.first?["id"] as? String, "m1")
    }

    func testReactMemoriesSettingsFieldsRoundTripsThroughZettelSettingsData() {
        let bridgeShape = ReactMemoriesSettingsFields(from: sampleSettings)
        let roundTripped = bridgeShape.asZettelSettingsData
        XCTAssertEqual(roundTripped, sampleSettings)
    }

    func testReactMemoriesSettingsFieldsDecodesRawJSDictionary() {
        let raw: [String: Any] = [
            "enabledSources": ["agent_task"],
            "historyDays": 7,
            "cardingEnabled": false,
            "cardingIntervalMinutes": 60,
            "limitPerSourcePerPass": 500,
            "narrativeEnabled": false,
            "narrativeModel": "",
            "narrativeMode": "continuous",
            "narrativeScheduledTime": "02:00",
            "narrativeIntervalMinutes": 120,
            "narrativeBatchSize": 50,
            "narrativeMaxAttempts": 3,
            "narrativeMaxRecords": 500,
        ]
        let decoded = ReactMemoriesSettingsFields(raw: raw)
        XCTAssertEqual(decoded?.historyDays, 7)
        XCTAssertEqual(decoded?.narrativeMode, "continuous")
        XCTAssertEqual(decoded?.narrativeMaxRecords, 500)
    }

    func testReactMemoriesSettingsFieldsRejectsMissingField() {
        let raw: [String: Any] = ["historyDays": 7]
        XCTAssertNil(ReactMemoriesSettingsFields(raw: raw))
    }

    func testReactMemoriesSettingsFieldsRejectsNilInput() {
        XCTAssertNil(ReactMemoriesSettingsFields(raw: nil))
    }
}
