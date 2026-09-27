import XCTest
@testable import BasilClient

/// Regression coverage for capture-anchored live-line timestamps.
@MainActor
final class LiveLineMergeTimelineAnchoringTests: XCTestCase {

    private func makeLine(
        text: String,
        timelineStartSeconds: Double?,
        timelineEndSeconds: Double? = nil,
        lineComplete: Bool = true
    ) -> TranscriptionLine {
        TranscriptionLine(
            id: UUID().uuidString,
            text: text,
            speakerID: nil,
            isInterim: false,
            start: nil,
            end: nil,
            diff: nil,
            timelineStartSeconds: timelineStartSeconds,
            timelineEndSeconds: timelineEndSeconds,
            source: nil,
            lineComplete: lineComplete
        )
    }

    func testDelayedFirstResponseUsesBackendPositionWithoutCreatingAnEpoch() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.recordingStartTime = Date().addingTimeInterval(-120.0)

        viewModel.appendLiveLines(
            [makeLine(text: "hello", timelineStartSeconds: 9.5, timelineEndSeconds: 9.8)],
            to: .microphone
        )
        let firstLine = viewModel.microphoneTranscript.last!
        XCTAssertEqual(firstLine.timelineStartSeconds, 9.5)
        XCTAssertEqual(firstLine.timelineEndSeconds, 9.8)
    }

    func testRapidBackendCatchUpIgnoresReceiptTime() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.recordingStartTime = Date().addingTimeInterval(-120.0)

        viewModel.appendLiveLines(
            [makeLine(text: "first.", timelineStartSeconds: 8.0, timelineEndSeconds: 8.4)],
            to: .microphone
        )
        viewModel.appendLiveLines(
            [makeLine(text: "second.", timelineStartSeconds: 10.0, timelineEndSeconds: 10.4)],
            to: .microphone
        )

        XCTAssertEqual(viewModel.microphoneTranscript.last?.timelineStartSeconds, 10.0)
        XCTAssertEqual(viewModel.microphoneTranscript.last?.timelineEndSeconds, 10.4)
    }

    func testMicrophoneAndSystemAudioRetainTheirDistinctBackendPositions() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.appendLiveLines(
            [makeLine(text: "mic line", timelineStartSeconds: 4.9)],
            to: .microphone
        )
        viewModel.appendLiveLines(
            [makeLine(text: "system line", timelineStartSeconds: 3.0)],
            to: .systemAudio
        )

        let micLine = viewModel.microphoneTranscript.last!
        let systemLine = viewModel.systemAudioTranscript.last!
        XCTAssertEqual(micLine.timelineStartSeconds, 4.9)
        XCTAssertEqual(systemLine.timelineStartSeconds, 3.0)
    }

    func testResumeTimelineOffsetIsAddedExactlyOnce() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.resumeTimelineOffsetSeconds = 120.0 // resumed part starts 2 minutes into the logical meeting

        viewModel.appendLiveLines(
            [makeLine(text: "resumed part line", timelineStartSeconds: 0.2)],
            to: .microphone
        )

        let line = viewModel.microphoneTranscript.last!
        XCTAssertEqual(line.timelineStartSeconds, 120.2)
    }

    func testMissingBackendPositionFallsBackToPassthroughWithoutCrashing() {
        let viewModel = LiveTranscriptionViewModel()

        viewModel.appendLiveLines(
            [makeLine(text: "no timeline info", timelineStartSeconds: nil)],
            to: .microphone
        )

        let line = viewModel.microphoneTranscript.last!
        XCTAssertEqual(line.text, "no timeline info")
        XCTAssertNil(line.timelineStartSeconds)
        XCTAssertEqual(line.source, .microphone)
    }
}
