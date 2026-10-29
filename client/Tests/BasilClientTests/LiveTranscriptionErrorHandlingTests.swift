import XCTest
@testable import BasilClient

/// Regression coverage for the unattributed-source branch of
/// `LiveTranscriptionViewModel.handleError(_:source:)`. That branch used to run
/// its own combined mic + system-audio reconnect against the shared
/// `microphoneReconnectAttempt` counter with no in-flight guard, so it could
/// race an already-running per-source recovery (`recoverMicrophoneWebSocket`),
/// double-spend the shared 6-attempt retry budget, and trip `stopRecording()`
/// (ending the meeting and starting post-processing) after only a couple of
/// real network blips instead of six. It now defers entirely to the same
/// guarded per-source recovery functions used for attributed drops.
@MainActor
final class LiveTranscriptionErrorHandlingTests: XCTestCase {
    private func timedOutError() -> NSError {
        NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "The request timed out."])
    }

    private func flushMainQueue() {
        let exp = expectation(description: "main queue flush")
        DispatchQueue.main.async { exp.fulfill() }
        wait(for: [exp], timeout: 1.0)
    }

    func testUnattributedErrorDoesNotDoubleSpendBudgetWhileMicRecoveryInFlight() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isRecording = true
        viewModel.enableMicrophone = true

        // Simulate a per-source mic recovery already in progress.
        viewModel.microphoneReconnectInFlight = true
        viewModel.microphoneReconnectAttempt = 3

        viewModel.handleError(timedOutError(), source: nil)
        flushMainQueue()

        XCTAssertEqual(
            viewModel.microphoneReconnectAttempt, 3,
            "An unattributed error arriving while a per-source mic recovery is already in flight must not touch the shared retry counter."
        )
        XCTAssertTrue(
            viewModel.isRecording,
            "The in-flight guard must prevent the unattributed-error path from tearing down an already-recovering session."
        )
    }

    func testUnattributedErrorRoutesThroughGuardedMicRecoveryWhenIdle() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isRecording = true
        viewModel.enableMicrophone = true
        viewModel.connectionState = .recording

        viewModel.handleError(timedOutError(), source: nil)
        flushMainQueue()

        XCTAssertTrue(
            viewModel.isRecording,
            "A single unattributed temporary error must not immediately stop recording."
        )
        XCTAssertTrue(
            viewModel.microphoneReconnectInFlight,
            "Idle unattributed errors should hand off to the guarded per-source mic recovery, arming its in-flight guard exactly once."
        )
        XCTAssertEqual(
            viewModel.microphoneReconnectAttempt, 1,
            "Routing through recoverMicrophoneWebSocket should increment the counter exactly once per call."
        )

        viewModel.microphoneWebSocketRecoveryTask?.cancel()
    }

    /// Mirrors the microphone chunk-send failure handler in
    /// `LiveTranscriptionViewModel+AudioEngine.swift`, which now calls
    /// `recoverMicrophoneWebSocket` directly (like the system-audio send-failure
    /// path already does in `LiveTranscriptionViewModel+SystemAudio.swift`)
    /// instead of routing through `handleError`'s generic, unattributed branch.
    /// A mic-only send failure must never touch system-audio recovery state.
    func testMicSendFailureRecoveryLeavesSystemAudioStateUntouched() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isRecording = true
        viewModel.systemAudioReconnectAttempt = 0
        viewModel.systemAudioReconnectInFlight = false

        viewModel.recoverMicrophoneWebSocket(reason: "send failed: socket is not connected")

        XCTAssertEqual(
            viewModel.microphoneReconnectAttempt, 1,
            "A mic send failure should arm the mic-only retry counter."
        )
        XCTAssertEqual(
            viewModel.systemAudioReconnectAttempt, 0,
            "A mic-only send failure must never touch the system-audio retry counter, so a healthy system-audio stream is left running undisturbed."
        )
        XCTAssertFalse(
            viewModel.systemAudioReconnectInFlight,
            "A mic-only send failure must never arm system-audio recovery."
        )
        XCTAssertTrue(viewModel.isRecording)

        viewModel.microphoneWebSocketRecoveryTask?.cancel()
    }
}
