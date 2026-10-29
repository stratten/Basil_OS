import XCTest
@testable import BasilClient

final class AnalysisViewTargetTests: XCTestCase {
    private func meeting(id: String, latestAnalysis: String?) throws -> MeetingListItem {
        var json: [String: Any] = [
            "id": id,
            "name": "Meeting \(id)",
            "participants": [String](),
            "start_time": "2026-10-27T15:00:00Z",
            "is_post_processed": true,
        ]
        if let latestAnalysis {
            json["analysis_summary"] = ["count": 1, "latest_filename": latestAnalysis, "latest_timestamp": "2026-10-27T16:00:00Z"]
        }
        return try JSONDecoder().decode(MeetingListItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func target(
        filename: String,
        requested: String? = nil,
        selected: String? = nil,
        active: String? = nil,
        history: [String] = [],
        meetings: [MeetingListItem] = [],
        failedOpen: (filename: String, meetingId: String)? = nil
    ) -> String? {
        LiveTranscriptionViewModel.analysisViewTargetMeetingId(
            filename: filename,
            requestedMeetingId: requested,
            selectedMeetingId: selected,
            activeAnalysisMeetingId: active,
            analysisHistoryFilenames: history,
            meetings: meetings,
            failedOpen: failedOpen
        )
    }

    func testARowQuickActionOpensItsOwnMeetingEvenWhenAnotherIsSelected() throws {
        let rows = [try meeting(id: "a", latestAnalysis: "a-latest.json"), try meeting(id: "b", latestAnalysis: "b-latest.json")]
        XCTAssertEqual(
            target(filename: "b-latest.json", requested: "b", selected: "a", history: ["a-latest.json"], meetings: rows),
            "b"
        )
    }

    func testARowQuickActionWorksWithNoMeetingSelected() throws {
        let rows = [try meeting(id: "b", latestAnalysis: "b-latest.json")]
        XCTAssertEqual(target(filename: "b-latest.json", requested: "b", meetings: rows), "b")
    }

    func testARequestNamingTheWrongFileForThatMeetingIsRejected() throws {
        let rows = [try meeting(id: "a", latestAnalysis: "a-latest.json"), try meeting(id: "b", latestAnalysis: "b-latest.json")]
        XCTAssertNil(target(filename: "a-latest.json", requested: "b", selected: "a", history: ["a-latest.json"], meetings: rows))
    }

    func testAnUnknownMeetingOrAMeetingWithoutAnAnalysisIsRejected() throws {
        let rows = [try meeting(id: "a", latestAnalysis: nil)]
        XCTAssertNil(target(filename: "x.json", requested: "a", meetings: rows))
        XCTAssertNil(target(filename: "x.json", requested: "missing", meetings: rows))
    }

    func testTheSelectedMeetingStillOpensFromItsLoadedHistoryBeforeTheRowSummaryCatchesUp() throws {
        let rows = [try meeting(id: "a", latestAnalysis: "a-old.json")]
        XCTAssertEqual(
            target(filename: "a-new.json", requested: "a", selected: "a", history: ["a-new.json", "a-old.json"], meetings: rows),
            "a"
        )
    }

    func testTheAnalysisTabViewButtonKeepsUsingTheSelectedMeetingsHistory() {
        XCTAssertEqual(target(filename: "one.json", selected: "a", history: ["one.json"]), "a")
        XCTAssertEqual(target(filename: "one.json", active: "live", history: ["one.json"]), "live")
        XCTAssertNil(target(filename: "other.json", selected: "a", history: ["one.json"]))
        XCTAssertNil(target(filename: "one.json", history: ["one.json"]))
    }

    func testRetryOfAFailedOpenReturnsToThatMeetingNotTheSelectedOne() {
        XCTAssertEqual(
            target(filename: "b-latest.json", selected: "a", history: ["a-latest.json"], failedOpen: ("b-latest.json", "b")),
            "b"
        )
        XCTAssertNil(target(filename: "c.json", selected: "a", history: ["a-latest.json"], failedOpen: ("b-latest.json", "b")))
    }

    func testTranscriptLinesMapToTheBridgeShape() {
        let line = TranscriptionLine(
            id: "1", text: "Hello", speakerID: "S1", isInterim: false, start: "1.00", end: "2.00", diff: 1,
            timelineStartSeconds: 1, timelineEndSeconds: 2, source: .systemAudio, lineComplete: true
        )
        let dto = LiveTranscriptionViewModel.transcriptLineDTOs(from: [line])
        XCTAssertEqual(dto.count, 1)
        XCTAssertEqual(dto[0].text, "Hello")
        XCTAssertEqual(dto[0].speakerId, "S1")
        XCTAssertEqual(dto[0].source, AudioSource.systemAudio.rawValue)
        XCTAssertEqual(dto[0].timelineStartSeconds, 1)
    }
}
