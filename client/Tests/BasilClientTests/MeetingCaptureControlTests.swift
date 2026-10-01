import XCTest
@testable import BasilClient

@MainActor
final class MeetingCaptureControlTests: XCTestCase {
    func testDisablingLiveTranscriptionWhileIdleSwitchesToRecordOnly() {
        let viewModel = LiveTranscriptionViewModel()
        XCTAssertEqual(viewModel.transcriptionState, .loadingModels)

        viewModel.setSessionLiveTranscriptionEnabled(false)

        XCTAssertFalse(viewModel.sessionLiveTranscriptionEnabled)
        XCTAssertTrue(viewModel.liveTranscriptionSelectionTouched)
        XCTAssertEqual(viewModel.transcriptionState, .idle, "record-only start must not wait for live models")
        XCTAssertEqual(viewModel.statusMessage, LiveTranscriptionViewModel.recordOnlyIdleStatusMessage)
        XCTAssertFalse(viewModel.liveTranscriptionWasDisabledThisPart, "not recording, so no part was affected")
    }

    func testResumedSystemAudioSegmentNeverOverwritesEarlierBackup() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("capture-control-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let first = LiveTranscriptionViewModel.systemAudioBackupFileURL(in: directory, baseName: "SystemAudio")
        XCTAssertEqual(first.deletingLastPathComponent().standardizedFileURL, directory.standardizedFileURL)
        try Data([1]).write(to: first)

        let second = LiveTranscriptionViewModel.systemAudioBackupFileURL(in: directory, baseName: "SystemAudio")
        XCTAssertNotEqual(first, second)
        XCTAssertFalse(FileManager.default.fileExists(atPath: second.path))
        XCTAssertEqual(second.pathExtension, "wav")
    }

    func testRecordingStatusMessageReflectsPauseAndLiveMode() {
        let viewModel = LiveTranscriptionViewModel()
        XCTAssertEqual(viewModel.recordingStatusMessage(), "Recording and transcribing...")
        viewModel.sessionLiveTranscriptionEnabled = false
        XCTAssertEqual(viewModel.recordingStatusMessage(), "Recording (live transcription off)")
        viewModel.isCapturePaused = true
        XCTAssertEqual(viewModel.recordingStatusMessage(), "Paused")
    }

    func testCaptureActionsAreNoOpsWhenNotRecording() async {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.pauseCapture()
        XCTAssertFalse(viewModel.isCapturePaused)
        XCTAssertFalse(viewModel.recordingClock.isPaused)

        await viewModel.resumeCapture()
        XCTAssertFalse(viewModel.isCapturePaused)

        await viewModel.cancelActiveRecording()
        XCTAssertFalse(viewModel.isRecording)

        viewModel.handleLiveTranscriptionUnavailable()
        XCTAssertTrue(viewModel.sessionLiveTranscriptionEnabled)
    }

    func testSnapshotCarriesCaptureControlState() {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        viewModel.isCapturePaused = true
        viewModel.sessionLiveTranscriptionEnabled = false
        publisher.sendSnapshot(to: token)

        let ui = events.last?.ui
        XCTAssertEqual(ui?.isCapturePaused, true)
        XCTAssertEqual(ui?.isLiveTranscriptionEnabled, false)
    }

    func testCaptureIntentsAreInTheClosedList() {
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "pauseRecording"), .pauseRecording)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "resumeRecording"), .resumeRecording)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "cancelRecording"), .cancelRecording)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "setLiveTranscription"), .setLiveTranscription)
    }
}
