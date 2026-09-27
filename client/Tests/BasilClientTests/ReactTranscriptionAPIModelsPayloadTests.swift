import XCTest
@testable import BasilClient

final class ReactTranscriptionAPIModelsPayloadTests: XCTestCase {
    func testMakeModelSummariesMarksNoneEnabledWhenListIsEmpty() {
        let summaries = TranscriptionApiModelsPayloadBuilder.makeModelSummaries(enabledModels: [])
        XCTAssertEqual(summaries.count, 3)
        for summary in summaries {
            XCTAssertEqual(summary["enabled"] as? Bool, false)
        }
    }

    func testMakeModelSummariesMarksOnlyMatchingIdsEnabled() {
        let enabled = [
            TranscriptionAPIModelInfo(
                id: "openai-gpt-4o-transcribe", name: "openai-gpt-4o-transcribe",
                displayName: "ignored", provider: "openai", isApiModel: true,
                description: nil, apiModelName: "gpt-4o-transcribe"
            )
        ]
        let summaries = TranscriptionApiModelsPayloadBuilder.makeModelSummaries(enabledModels: enabled)
        let byId = Dictionary(uniqueKeysWithValues: summaries.map { ($0["id"] as! String, $0) })
        XCTAssertEqual(byId["openai-whisper-1"]?["enabled"] as? Bool, false)
        XCTAssertEqual(byId["openai-gpt-4o-transcribe"]?["enabled"] as? Bool, true)
        XCTAssertEqual(byId["openai-gpt-4o-mini-transcribe"]?["enabled"] as? Bool, false)
    }

    func testMakeModelSummariesPreservesCatalogOrderAndDisplayFields() {
        let summaries = TranscriptionApiModelsPayloadBuilder.makeModelSummaries(enabledModels: [])
        let ids = summaries.map { $0["id"] as! String }
        XCTAssertEqual(ids, ["openai-whisper-1", "openai-gpt-4o-transcribe", "openai-gpt-4o-mini-transcribe"])
        XCTAssertEqual(summaries[0]["displayName"] as? String, "Whisper (OpenAI API)")
        XCTAssertEqual(
            summaries[0]["description"] as? String,
            "OpenAI's hosted Whisper model -- proven, reliable transcription"
        )
    }

    func testMakeModelSummariesIgnoresUnknownEnabledIds() {
        let enabled = [
            TranscriptionAPIModelInfo(
                id: "openai-gpt-4o-transcribe-diarize", name: "openai-gpt-4o-transcribe-diarize",
                displayName: "ignored", provider: "openai", isApiModel: true,
                description: nil, apiModelName: "gpt-4o-transcribe-diarize"
            )
        ]
        let summaries = TranscriptionApiModelsPayloadBuilder.makeModelSummaries(enabledModels: enabled)
        XCTAssertEqual(summaries.count, 3)
        for summary in summaries {
            XCTAssertEqual(summary["enabled"] as? Bool, false)
        }
    }
}
