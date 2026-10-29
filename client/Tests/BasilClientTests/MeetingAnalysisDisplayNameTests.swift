import XCTest
@testable import BasilClient

final class MeetingAnalysisDisplayNameTests: XCTestCase {
    func testRenamedMeetingShowsItsCurrentNameInsteadOfTheStoredAnalysisName() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: "Meeting 2026-10-13 15:13",
            resultMeetingId: "meeting-1",
            viewedMeetingIds: ["meeting-1", nil],
            currentName: "Weekly Check-in"
        )
        XCTAssertEqual(name, "Weekly Check-in")
    }

    func testCurrentNameMatchesTheLiveMeetingWhenNoPastMeetingIsSelected() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: "Old name",
            resultMeetingId: "live-1",
            viewedMeetingIds: [nil, "live-1"],
            currentName: "  New name  "
        )
        XCTAssertEqual(name, "New name")
    }

    func testResultForADifferentMeetingKeepsItsStoredName() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: "Other meeting",
            resultMeetingId: "meeting-2",
            viewedMeetingIds: ["meeting-1", "live-1"],
            currentName: "Weekly Check-in"
        )
        XCTAssertEqual(name, "Other meeting")
    }

    func testBlankCurrentNameKeepsTheStoredName() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: "Stored",
            resultMeetingId: "meeting-1",
            viewedMeetingIds: ["meeting-1"],
            currentName: "   "
        )
        XCTAssertEqual(name, "Stored")
    }

    func testResultWithoutAMeetingIdKeepsItsStoredName() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: "Stored",
            resultMeetingId: nil,
            viewedMeetingIds: [nil, nil],
            currentName: "Current"
        )
        XCTAssertEqual(name, "Stored")
    }

    func testMissingStoredNameStillGetsTheCurrentName() {
        let name = LiveTranscriptionViewModel.analysisDisplayName(
            storedName: nil,
            resultMeetingId: "meeting-1",
            viewedMeetingIds: ["meeting-1"],
            currentName: "Weekly Check-in"
        )
        XCTAssertEqual(name, "Weekly Check-in")
    }

    func testRevisedPurposeReplacesTheStoredPurposeAndAClearedPurposeRemovesIt() {
        XCTAssertEqual(
            LiveTranscriptionViewModel.analysisDisplayPurpose(
                storedPurpose: "Old purpose",
                resultMeetingId: "meeting-1",
                viewedMeetingIds: ["meeting-1"],
                currentPurpose: " Plan the launch "
            ),
            "Plan the launch"
        )
        XCTAssertNil(
            LiveTranscriptionViewModel.analysisDisplayPurpose(
                storedPurpose: "Old purpose",
                resultMeetingId: "meeting-1",
                viewedMeetingIds: ["meeting-1"],
                currentPurpose: "  "
            )
        )
    }

    func testPurposeOfADifferentMeetingIsLeftAlone() {
        XCTAssertEqual(
            LiveTranscriptionViewModel.analysisDisplayPurpose(
                storedPurpose: "Stored",
                resultMeetingId: "meeting-2",
                viewedMeetingIds: ["meeting-1"],
                currentPurpose: "Current"
            ),
            "Stored"
        )
        XCTAssertEqual(
            LiveTranscriptionViewModel.analysisDisplayPurpose(
                storedPurpose: "Stored",
                resultMeetingId: nil,
                viewedMeetingIds: [nil],
                currentPurpose: "Current"
            ),
            "Stored"
        )
    }

    func testRevisedParticipantsAreParsedTrimmedAndAnEmptiedFieldRemovesTheStoredList() {
        XCTAssertEqual(
            LiveTranscriptionViewModel.analysisDisplayParticipants(
                storedParticipants: ["old@example.com"],
                resultMeetingId: "meeting-1",
                viewedMeetingIds: [nil, "meeting-1"],
                currentParticipants: " ada@example.com ,, Grace Hopper ,"
            ),
            ["ada@example.com", "Grace Hopper"]
        )
        XCTAssertNil(
            LiveTranscriptionViewModel.analysisDisplayParticipants(
                storedParticipants: ["old@example.com"],
                resultMeetingId: "meeting-1",
                viewedMeetingIds: ["meeting-1"],
                currentParticipants: ""
            )
        )
    }

    func testParticipantsOfADifferentMeetingAreLeftAlone() {
        XCTAssertEqual(
            LiveTranscriptionViewModel.analysisDisplayParticipants(
                storedParticipants: ["stored@example.com"],
                resultMeetingId: "meeting-2",
                viewedMeetingIds: ["meeting-1"],
                currentParticipants: "current@example.com"
            ),
            ["stored@example.com"]
        )
    }

    // MARK: - Meeting date

    private func listItem(id: String, startTime: String) -> MeetingListItem {
        MeetingListItem(
            id: id,
            name: "Meeting",
            purpose: nil,
            participants: [],
            startTime: startTime,
            endTime: nil,
            durationSeconds: 60,
            audioPath: nil,
            transcriptPath: nil,
            isPostProcessed: false,
            analysisSummary: nil,
            sessionId: nil,
            audioSource: nil,
            members: nil
        )
    }

    func testStoredMeetingDateWinsOverTheLoadedHistoryEntry() {
        let date = LiveTranscriptionViewModel.analysisDisplayMeetingDate(
            storedFormattedDate: "2026-01-23 3:45 pm",
            resultMeetingId: "meeting-1",
            loadedMeetings: [listItem(id: "meeting-1", startTime: "2026-02-01T09:00:00")],
            style: .absolute
        )
        XCTAssertEqual(date, "2026-01-23 3:45 pm")
    }

    func testOlderAnalysisFallsBackToTheLoadedMeetingsStartTime() {
        let date = LiveTranscriptionViewModel.analysisDisplayMeetingDate(
            storedFormattedDate: nil,
            resultMeetingId: "meeting-1",
            loadedMeetings: [listItem(id: "meeting-2", startTime: "2026-03-01T08:00:00"), listItem(id: "meeting-1", startTime: "2026-02-01T09:00:00")],
            style: .absolute
        )
        XCTAssertEqual(date, "2026-02-01 9:00 am")
    }

    func testNoDateWhenTheMeetingIsNotLoadedAndNothingWasStored() {
        XCTAssertNil(
            LiveTranscriptionViewModel.analysisDisplayMeetingDate(
                storedFormattedDate: nil,
                resultMeetingId: "meeting-9",
                loadedMeetings: [listItem(id: "meeting-1", startTime: "2026-02-01T09:00:00")],
                style: .absolute
            )
        )
        XCTAssertNil(
            LiveTranscriptionViewModel.analysisDisplayMeetingDate(
                storedFormattedDate: "",
                resultMeetingId: nil,
                loadedMeetings: [],
                style: .absolute
            )
        )
    }
}
