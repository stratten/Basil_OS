import XCTest
@testable import BasilClient

final class TranscriptTimelineSpliceTests: XCTestCase {

    private func line(_ start: Double, _ end: Double, _ text: String) -> TranscriptionLine {
        TranscriptionLine(
            id: UUID().uuidString,
            text: text,
            speakerID: nil,
            isInterim: false,
            start: nil,
            end: nil,
            diff: end - start,
            timelineStartSeconds: start,
            timelineEndSeconds: end
        )
    }

    // MARK: - nextCheckpointEnd

    func testNoCheckpointBeforeFirstFullInterval() {
        XCTAssertNil(TranscriptTimelineSplice.nextCheckpointEnd(elapsed: 59, interval: 60, lastCheckpoint: 0))
    }

    func testCheckpointAtFirstFullInterval() {
        XCTAssertEqual(TranscriptTimelineSplice.nextCheckpointEnd(elapsed: 60, interval: 60, lastCheckpoint: 0), 60)
    }

    func testCheckpointAdvancesPastLast() {
        XCTAssertEqual(TranscriptTimelineSplice.nextCheckpointEnd(elapsed: 125, interval: 60, lastCheckpoint: 60), 120)
    }

    func testNoNewCheckpointWhenSameBoundary() {
        // 125s elapsed already covered by the 120 checkpoint -> no new window.
        XCTAssertNil(TranscriptTimelineSplice.nextCheckpointEnd(elapsed: 125, interval: 60, lastCheckpoint: 120))
    }

    func testZeroIntervalIsSafe() {
        XCTAssertNil(TranscriptTimelineSplice.nextCheckpointEnd(elapsed: 100, interval: 0, lastCheckpoint: 0))
    }

    // MARK: - planOnStopWindow

    func testOnStopTailWhenThresholdsRan() {
        let window = TranscriptTimelineSplice.planOnStopWindow(thresholdsEnabled: true, lastCheckpoint: 600, total: 745)
        XCTAssertEqual(window.start, 600)
        XCTAssertEqual(window.end, 745)
    }

    func testOnStopFullWhenThresholdsDisabled() {
        let window = TranscriptTimelineSplice.planOnStopWindow(thresholdsEnabled: false, lastCheckpoint: 600, total: 745)
        XCTAssertEqual(window.start, 0)
        XCTAssertEqual(window.end, 745)
    }

    func testOnStopFullWhenNoCheckpointYet() {
        let window = TranscriptTimelineSplice.planOnStopWindow(thresholdsEnabled: true, lastCheckpoint: 0, total: 300)
        XCTAssertEqual(window.start, 0)
        XCTAssertEqual(window.end, 300)
    }

    // MARK: - spliceByRange

    func testSpliceReplacesOverlappingRangeOnly() {
        let existing = [line(0, 10, "a"), line(10, 20, "b"), line(20, 30, "c")]
        let new = [line(10, 15, "B1"), line(15, 20, "B2")]
        let result = TranscriptTimelineSplice.spliceByRange(existing: existing, newLines: new, start: 10, end: 20)
        XCTAssertEqual(result.map(\.text), ["a", "B1", "B2", "c"])
    }

    func testSpliceKeepsBoundaryAdjacentLines() {
        // A line ending exactly at `start` does not overlap [start, end).
        let existing = [line(0, 10, "a"), line(20, 30, "c")]
        let new = [line(10, 20, "B")]
        let result = TranscriptTimelineSplice.spliceByRange(existing: existing, newLines: new, start: 10, end: 20)
        XCTAssertEqual(result.map(\.text), ["a", "B", "c"])
    }

    func testSpliceKeepsLinesWithoutTimeline() {
        let untimed = TranscriptionLine(
            id: UUID().uuidString, text: "untimed", speakerID: nil, isInterim: false,
            start: nil, end: nil, diff: nil, timelineStartSeconds: nil, timelineEndSeconds: nil
        )
        let existing = [untimed, line(10, 20, "b")]
        let new = [line(10, 20, "B")]
        let result = TranscriptTimelineSplice.spliceByRange(existing: existing, newLines: new, start: 10, end: 20)
        XCTAssertTrue(result.contains { $0.text == "untimed" })
        XCTAssertTrue(result.contains { $0.text == "B" })
        XCTAssertFalse(result.contains { $0.text == "b" })
    }

    func testSpliceResolvesLegacyTimeStrings() {
        let legacy = TranscriptionLine(
            id: UUID().uuidString, text: "legacy", speakerID: nil, isInterim: false,
            start: "0:15", end: "0:18", diff: 3, timelineStartSeconds: nil, timelineEndSeconds: nil
        )
        let new = [line(10, 20, "B")]
        let result = TranscriptTimelineSplice.spliceByRange(existing: [legacy], newLines: new, start: 10, end: 20)
        // 15-18s overlaps [10,20) -> replaced.
        XCTAssertEqual(result.map(\.text), ["B"])
    }

    func testSplicePreservesOutsideWindowRowIdentity() {
        let before = line(0, 10, "before")
        let after = line(30, 40, "after")
        let existing = [before, line(10, 20, "old"), after]
        let new = [line(10, 20, "new")]

        let result = TranscriptTimelineSplice.spliceByRange(existing: existing, newLines: new, start: 10, end: 20)

        XCTAssertEqual(result.first?.id, before.id)
        XCTAssertEqual(result.last?.id, after.id)
        XCTAssertEqual(result.map(\.text), ["before", "new", "after"])
    }

    func testDeterministicSegmentIDIsStableForEquivalentWindowSegments() {
        let first = TranscriptTimelineSplice.deterministicSegmentID(
            source: .microphone,
            timelineStartSeconds: 12.3454,
            timelineEndSeconds: 18.0001,
            speakerID: "Speaker 1"
        )
        let second = TranscriptTimelineSplice.deterministicSegmentID(
            source: .microphone,
            timelineStartSeconds: 12.3454,
            timelineEndSeconds: 18.0001,
            speakerID: "Speaker 1"
        )

        XCTAssertEqual(first, second)
    }

    func testDeterministicSegmentIDDifferentiatesSources() {
        let microphone = TranscriptTimelineSplice.deterministicSegmentID(
            source: .microphone,
            timelineStartSeconds: 12,
            timelineEndSeconds: 18,
            speakerID: nil
        )
        let system = TranscriptTimelineSplice.deterministicSegmentID(
            source: .systemAudio,
            timelineStartSeconds: 12,
            timelineEndSeconds: 18,
            speakerID: nil
        )

        XCTAssertNotEqual(microphone, system)
    }

    func testParseTimeStringFormats() {
        XCTAssertEqual(TranscriptTimelineSplice.parseTimeString("1:02:03"), 3723)
        XCTAssertEqual(TranscriptTimelineSplice.parseTimeString("02:05"), 125)
        XCTAssertEqual(TranscriptTimelineSplice.parseTimeString("42"), 42)
        XCTAssertNil(TranscriptTimelineSplice.parseTimeString(""))
    }
}
