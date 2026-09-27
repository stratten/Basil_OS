import XCTest
@testable import BasilClient

final class MeetingAnalysisResultDTOBuilderTests: XCTestCase {
    private func makeResult() -> MeetingAnalysisResult {
        let json = """
        {
            "meeting_id": "meeting-1",
            "analyzed_at": "2026-08-14 10:00",
            "model_used": "local-model",
            "modes_analyzed": ["summary"],
            "summary": "The team agreed to ship Friday.",
            "transcript_duration": 125,
            "speaker_count": 2,
            "processing_time": 4.2
        }
        """
        return try! JSONDecoder().decode(MeetingAnalysisResult.self, from: Data(json.utf8))
    }

    func testTranscriptIsOmittedWhenNoLinesAreSupplied() {
        let dto = MeetingAnalysisResultDTOBuilder.build(makeResult(), filename: "analysis.json")
        XCTAssertNil(dto.transcript)
    }

    func testTranscriptPassesThroughWhenLinesAreSupplied() {
        let lines = [
            TranscriptLineDTO(
                id: "1",
                text: "Let's ship Friday.",
                speakerId: nil,
                isInterim: false,
                displayStart: "0:00:05",
                timelineStartSeconds: 5,
                timelineEndSeconds: 6,
                source: "Microphone",
                lineComplete: true
            ),
        ]
        let dto = MeetingAnalysisResultDTOBuilder.build(makeResult(), filename: "analysis.json", transcript: lines)
        XCTAssertEqual(dto.transcript, lines)
    }
}
