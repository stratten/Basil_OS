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

    // MARK: - Meeting date

    private func makeResult(meetingStartTime: String?) -> MeetingAnalysisResult {
        let startField = meetingStartTime.map { "\"meeting_start_time\": \"\($0)\"," } ?? ""
        let json = """
        {
            "meeting_id": "meeting-1",
            "analyzed_at": "2026-08-14 10:00",
            \(startField)
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

    func testMeetingStartTimeDecodesFromTheBackendFieldAndFormatsWithTheSharedFormatter() {
        let timestamp = "2026-01-23T15:45:00Z"
        let result = makeResult(meetingStartTime: timestamp)
        XCTAssertEqual(result.meetingStartTime, timestamp)

        let originalStyle = DateDisplayPreferenceStore.shared.style
        defer { DateDisplayPreferenceStore.shared.update(originalStyle) }
        DateDisplayPreferenceStore.shared.update(.absolute)

        let dto = MeetingAnalysisResultDTOBuilder.build(result, filename: "analysis.json")
        XCTAssertEqual(dto.meetingFormattedDate, DateFormattingUtils.formatTimestamp(timestamp, style: .absolute))
    }

    func testAbsoluteStyleMatchesTheHistoryListFormat() {
        XCTAssertEqual(
            MeetingAnalysisResultDTOBuilder.formattedMeetingDate(startTime: "2026-01-23T15:45:00", style: .absolute),
            "2026-01-23 3:45 pm"
        )
    }

    func testMeetingDateIsNilForAnAnalysisSavedBeforeTheBackendRecordedIt() {
        let dto = MeetingAnalysisResultDTOBuilder.build(makeResult(meetingStartTime: nil), filename: "analysis.json")
        XCTAssertNil(dto.meetingFormattedDate)
    }

    func testMeetingDateIsNilForBlankOrUnparseableStartTimesInsteadOfShowingARawString() {
        XCTAssertNil(MeetingAnalysisResultDTOBuilder.formattedMeetingDate(startTime: nil, style: .absolute))
        XCTAssertNil(MeetingAnalysisResultDTOBuilder.formattedMeetingDate(startTime: "   ", style: .absolute))
        XCTAssertNil(MeetingAnalysisResultDTOBuilder.formattedMeetingDate(startTime: "not a date", style: .relative))
    }
}
