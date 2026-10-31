import XCTest
@testable import BasilClient

/// Verifies that every view-model property the system-audio send decision depends on is mirrored into the off-main sender's gate. A missed mirror would either silence system audio or let it leak past a pause.
@MainActor
final class SystemAudioSenderGateMirroringTests: XCTestCase {
    func testGateStartsClosedAndMirrorsEachProperty() {
        let viewModel = LiveTranscriptionViewModel()
        let initial = viewModel.systemAudioSender.currentGate()
        XCTAssertFalse(initial.isRecording)
        XCTAssertFalse(initial.isReconnectInFlight)
        XCTAssertFalse(initial.isCapturePaused)
        XCTAssertFalse(initial.isStreamTimingReady)
        XCTAssertNil(initial.transport)

        viewModel.isRecording = true
        XCTAssertTrue(viewModel.systemAudioSender.currentGate().isRecording)
        viewModel.isRecording = false
        XCTAssertFalse(viewModel.systemAudioSender.currentGate().isRecording)

        viewModel.isCapturePaused = true
        XCTAssertTrue(viewModel.systemAudioSender.currentGate().isCapturePaused)
        viewModel.isCapturePaused = false
        XCTAssertFalse(viewModel.systemAudioSender.currentGate().isCapturePaused)

        viewModel.systemAudioReconnectInFlight = true
        XCTAssertTrue(viewModel.systemAudioSender.currentGate().isReconnectInFlight)
        viewModel.systemAudioReconnectInFlight = false
        XCTAssertFalse(viewModel.systemAudioSender.currentGate().isReconnectInFlight)

        viewModel.systemAudioStreamTimingReady = true
        XCTAssertTrue(viewModel.systemAudioSender.currentGate().isStreamTimingReady)
        viewModel.systemAudioStreamTimingReady = false
        XCTAssertFalse(viewModel.systemAudioSender.currentGate().isStreamTimingReady)
    }

    func testGateTransportFollowsTheWebSocketTaskIncludingClearing() throws {
        let viewModel = LiveTranscriptionViewModel()
        let url = try XCTUnwrap(URL(string: "ws://127.0.0.1:9/never-resumed"))
        let task = URLSession.shared.webSocketTask(with: url)

        viewModel.systemAudioWebSocketTask = task
        XCTAssertTrue(viewModel.systemAudioSender.currentGate().transport === task)

        viewModel.systemAudioWebSocketTask = nil
        XCTAssertNil(viewModel.systemAudioSender.currentGate().transport, "A cleared task must stop receiving audio immediately")
    }
}
