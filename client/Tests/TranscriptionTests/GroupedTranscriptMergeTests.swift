import XCTest
@testable import BasilClient

/// Unit tests for the pure grouped-transcript merge + live resume-offset logic.
///
/// These cover the issue-1b reopen bug (only the last part survived) and the
/// issue-1a live append-offset behavior, validated against the real on-disk
/// session `C1A17B7F` shape:
///   part0 mic 10.6→2124, part0 sys 1→585, part1 mic 2124→2572, part1 sys 2125→2585.
final class GroupedTranscriptMergeTests: XCTestCase {

    // Reference epoch for member start dates.
    private let base = Date(timeIntervalSinceReferenceDate: 0)

    private func line(_ timelineStart: Double, _ timelineEnd: Double, _ text: String, source: AudioSource) -> TranscriptionLine {
        TranscriptionLine(
            id: UUID().uuidString,
            text: text,
            speakerID: nil,
            isInterim: false,
            start: String(format: "%.2f", timelineStart),
            end: String(format: "%.2f", timelineEnd),
            diff: timelineEnd - timelineStart,
            timelineStartSeconds: timelineStart,
            timelineEndSeconds: timelineEnd,
            source: source,
            lineComplete: true
        )
    }

    private func member(_ source: AudioSource, part: Int, startOffset: Double, lines: [TranscriptionLine]) -> GroupedTranscriptMerge.MemberInput {
        GroupedTranscriptMerge.MemberInput(
            source: source,
            recordingPartIndex: part,
            startDate: base.addingTimeInterval(startOffset),
            lines: lines
        )
    }

    // MARK: - merge: accumulation (issue 1b)

    func testResumedFourMemberSessionKeepsAllParts() {
        let members: [GroupedTranscriptMerge.MemberInput] = [
            member(.microphone, part: 0, startOffset: 0, lines: [
                line(10.6, 600, "p0 mic a", source: .microphone),
                line(600, 2124, "p0 mic b", source: .microphone),
            ]),
            member(.systemAudio, part: 0, startOffset: 0, lines: [
                line(1, 585, "p0 sys", source: .systemAudio),
            ]),
            member(.microphone, part: 1, startOffset: 2124, lines: [
                line(2124.1, 2572.1, "p1 mic", source: .microphone),
            ]),
            member(.systemAudio, part: 1, startOffset: 2124, lines: [
                line(2125, 2585, "p1 sys", source: .systemAudio),
            ]),
        ]

        let merged = GroupedTranscriptMerge.merge(members)

        // Part 0 must NOT be dropped (the prior overwrite bug kept only part 1).
        XCTAssertEqual(merged.microphone.count, 3, "all mic parts accumulate")
        XCTAssertEqual(merged.systemAudio.count, 2, "all system parts accumulate")
        XCTAssertEqual(merged.microphone.first?.text, "p0 mic a", "part 0 mic present and first")
        XCTAssertEqual(merged.microphone.last?.text, "p1 mic", "part 1 mic present and last")
        XCTAssertEqual(merged.systemAudio.first?.text, "p0 sys", "part 0 sys present (the stalled track)")
        XCTAssertEqual(merged.systemAudio.last?.text, "p1 sys", "part 1 sys present")
    }

    func testNoDoubleOffsetForResumedPart() {
        // Persisted part-1 times already include the +2124 resume offset; merge
        // must not re-add a wall-clock offset (which would push it to ~5092).
        let members: [GroupedTranscriptMerge.MemberInput] = [
            member(.microphone, part: 0, startOffset: 0, lines: [
                line(10.6, 2124, "p0", source: .microphone),
            ]),
            member(.microphone, part: 1, startOffset: 2124, lines: [
                line(2124.1, 2572.1, "p1", source: .microphone),
            ]),
        ]

        let merged = GroupedTranscriptMerge.merge(members)

        XCTAssertEqual(merged.microphone.count, 2)
        XCTAssertEqual(merged.microphone[1].timelineStartSeconds ?? -1, 2124.1, accuracy: 0.001,
                       "resumed part keeps its persisted time, no double offset")
    }

    // MARK: - merge: cross-track skew within a part

    func testCrossTrackSkewWithinPartApplied() {
        // System audio for the same part started 3s after the microphone; its
        // lines must shift by +3 so the interleave reflects true relative timing.
        let members: [GroupedTranscriptMerge.MemberInput] = [
            member(.microphone, part: 0, startOffset: 0, lines: [
                line(10, 20, "mic", source: .microphone),
            ]),
            member(.systemAudio, part: 0, startOffset: 3, lines: [
                line(5, 9, "sys", source: .systemAudio),
            ]),
        ]

        let merged = GroupedTranscriptMerge.merge(members)

        XCTAssertEqual(merged.microphone.first?.timelineStartSeconds ?? -1, 10, accuracy: 0.001,
                       "earliest member in part is the skew origin (no shift)")
        XCTAssertEqual(merged.systemAudio.first?.timelineStartSeconds ?? -1, 8, accuracy: 0.001,
                       "later-starting track shifted by its skew (5 + 3)")
        XCTAssertEqual(merged.systemAudio.first?.timelineEndSeconds ?? -1, 12, accuracy: 0.001)
    }

    func testLegacySinglePartReducesToPriorBehavior() {
        // Single part, two synchronized sources -> no skew, values unchanged.
        let members: [GroupedTranscriptMerge.MemberInput] = [
            member(.microphone, part: 0, startOffset: 0, lines: [
                line(10, 20, "mic", source: .microphone),
            ]),
            member(.systemAudio, part: 0, startOffset: 0, lines: [
                line(12, 22, "sys", source: .systemAudio),
            ]),
        ]

        let merged = GroupedTranscriptMerge.merge(members)

        XCTAssertEqual(merged.microphone.first?.timelineStartSeconds ?? -1, 10, accuracy: 0.001)
        XCTAssertEqual(merged.systemAudio.first?.timelineStartSeconds ?? -1, 12, accuracy: 0.001)
    }

    func testMissingStartDatesYieldZeroSkew() {
        // Members without start dates must not crash and must not be shifted.
        let members: [GroupedTranscriptMerge.MemberInput] = [
            GroupedTranscriptMerge.MemberInput(
                source: .microphone, recordingPartIndex: 0, startDate: nil,
                lines: [line(10, 20, "mic", source: .microphone)]
            ),
        ]

        let merged = GroupedTranscriptMerge.merge(members)
        XCTAssertEqual(merged.microphone.first?.timelineStartSeconds ?? -1, 10, accuracy: 0.001)
    }

    // MARK: - liveResumeTimelineSeconds (issue 1a)

    func testLiveResumeTimelineSecondsAddsOffset() {
        // Backend format_time = str(timedelta) -> "H:MM:SS"; "0:02:05" = 125s.
        let value = GroupedTranscriptMerge.liveResumeTimelineSeconds(startString: "0:02:05", offset: 2124)
        XCTAssertEqual(value ?? -1, 2249, accuracy: 0.001)
    }

    func testLiveResumeTimelineSecondsNilForUnparseable() {
        XCTAssertNil(GroupedTranscriptMerge.liveResumeTimelineSeconds(startString: nil, offset: 2124))
        XCTAssertNil(GroupedTranscriptMerge.liveResumeTimelineSeconds(startString: "abc", offset: 2124))
    }

    func testParseTimeStringFormats() {
        XCTAssertEqual(GroupedTranscriptMerge.parseTimeString("1:02:05") ?? -1, 3725, accuracy: 0.001)
        XCTAssertEqual(GroupedTranscriptMerge.parseTimeString("10:00") ?? -1, 600, accuracy: 0.001)
        XCTAssertEqual(GroupedTranscriptMerge.parseTimeString("5") ?? -1, 5, accuracy: 0.001)
        XCTAssertNil(GroupedTranscriptMerge.parseTimeString("not:a:time"))
    }

    // MARK: - Resume live-line ordering (mirrors updateCombinedTranscript sort)

    /// Mirrors `LiveTranscriptionViewModel.timelineSortSeconds`: canonical
    /// seconds when present, else the parsed legacy `start` string.
    private func sortSeconds(_ l: TranscriptionLine) -> Double? {
        if let t = l.timelineStartSeconds { return t }
        if let s = l.start { return GroupedTranscriptMerge.parseTimeString(s) }
        return nil
    }

    private func sortedByTimeline(_ lines: [TranscriptionLine]) -> [TranscriptionLine] {
        lines.enumerated().sorted { left, right in
            switch (sortSeconds(left.element), sortSeconds(right.element)) {
            case let (lhs?, rhs?):
                return lhs == rhs ? left.offset < right.offset : lhs < rhs
            case (_?, nil): return true
            case (nil, _?): return false
            case (nil, nil): return left.offset < right.offset
            }
        }.map(\.element)
    }

    func testStampedResumedLiveLineSortsAfterRetainedHistory() {
        // Retained prior-part line at 2124s; a freshly resumed live line at
        // part-relative 5s stamped with offset 2124 -> 2129s sorts AFTER it.
        let retained = line(2124, 2124, "history tail", source: .microphone)
        let stamped = GroupedTranscriptMerge.liveResumeTimelineSeconds(startString: "0:00:05", offset: 2124)
        let live = TranscriptionLine(
            id: UUID().uuidString, text: "resumed", speakerID: nil, isInterim: false,
            start: "0:00:05", end: "0:00:06", diff: 1,
            timelineStartSeconds: stamped, timelineEndSeconds: nil,
            source: .microphone, lineComplete: false
        )

        let ordered = sortedByTimeline([live, retained])
        XCTAssertEqual(ordered.first?.text, "history tail")
        XCTAssertEqual(ordered.last?.text, "resumed", "stamped resumed line sorts after retained history")
    }

    func testUnstampedResumedLiveLineRegressesBeforeHistory() {
        // Negative/regression demonstration: WITHOUT the resume-offset stamp the
        // part-relative live line (5s) sorts BEFORE the retained 2124s history,
        // which is exactly the interleave bug the stamping fixes.
        let retained = line(2124, 2124, "history tail", source: .microphone)
        let liveUnstamped = TranscriptionLine(
            id: UUID().uuidString, text: "resumed", speakerID: nil, isInterim: false,
            start: "0:00:05", end: "0:00:06", diff: 1,
            timelineStartSeconds: nil, timelineEndSeconds: nil,
            source: .microphone, lineComplete: false
        )

        let ordered = sortedByTimeline([retained, liveUnstamped])
        XCTAssertEqual(ordered.first?.text, "resumed", "unstamped live line wrongly sorts before history")
    }
}
