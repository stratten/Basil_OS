import XCTest
@testable import BasilClient

/// Regression coverage for the microphone/system-audio connection setup in
/// `LiveTranscriptionViewModel.startRecording()`. That setup used to run
/// strictly sequentially (mic WebSocket wait, then system audio WebSocket
/// setup including an unconditional 500ms sleep), so the visible
/// ready -> recording delay was the SUM of both instead of the slower of the
/// two. It now runs both concurrently via `connectMicrophoneForRecording()`
/// and `connectSystemAudioForRecording()`, and the system-audio socket waits
/// for a real first message instead of a blind fixed sleep.
@MainActor
final class LiveTranscriptionRecordingStartConcurrencyTests: XCTestCase {
    private func flushMainQueue() {
        let exp = expectation(description: "main queue flush")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
    }

    func testStartRecordingWithNoAudioSourceEnabledNeverArmsEitherConnectionTask() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.enableMicrophone = false
        viewModel.isSystemAudioAvailable = false

        viewModel.startRecording()
        flushMainQueue()

        XCTAssertFalse(
            viewModel.isRecording,
            "Starting recording with no audio source enabled must not begin a recording session."
        )
        XCTAssertNil(
            viewModel.connectionTask,
            "The no-audio-source guard must return before either connection task is armed."
        )
        XCTAssertNil(
            viewModel.systemAudioConnectionTask,
            "The no-audio-source guard must return before either connection task is armed."
        )
        XCTAssertEqual(
            viewModel.statusMessage, "Please enable at least one audio source",
            "The existing no-audio-source guard message must be preserved by the concurrency refactor."
        )
    }

    func testStopRecordingCancelsSystemAudioConnectionTask() {
        let viewModel = LiveTranscriptionViewModel()

        // Simulate a system-audio connection wait still in flight, mirroring
        // the new readiness-wait task armed by startSystemAudioWebSocketConnection().
        let pendingConnection = Task {
            try await Task.sleep(nanoseconds: 30_000_000_000)
        }
        viewModel.systemAudioConnectionTask = pendingConnection

        viewModel.stopRecording()

        XCTAssertNil(
            viewModel.systemAudioConnectionTask,
            "stopRecording() must clear the system-audio connection task alongside the microphone one, or a stale readiness wait from a prior session could leak past the stop."
        )
        XCTAssertTrue(
            pendingConnection.isCancelled,
            "stopRecording() must cancel any in-flight system-audio connection wait."
        )
    }

    func testFreshAndResumePreparationClearStreamTimingReadiness() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.microphoneStreamTimingReady = true
        viewModel.systemAudioStreamTimingReady = true

        viewModel.prepareFreshRecordingSession()

        XCTAssertFalse(viewModel.microphoneStreamTimingReady)
        XCTAssertFalse(viewModel.systemAudioStreamTimingReady)

        viewModel.microphoneStreamTimingReady = true
        viewModel.systemAudioStreamTimingReady = true
        viewModel.prepareResumeRecordingSession(
            sessionId: "session",
            timelineOffsetSeconds: 10,
            recordingPartIndex: 1,
            resumedFromMeetingId: "previous"
        )

        XCTAssertFalse(viewModel.microphoneStreamTimingReady)
        XCTAssertFalse(viewModel.systemAudioStreamTimingReady)
    }
}
