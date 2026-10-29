import XCTest
@testable import BasilClient

@MainActor
final class MockTranscriptionAudioCaptureController: TranscriptionAudioCaptureControlling {
    var startCallCount = 0
    var cancelCallCount = 0
    var stopCallCount = 0
    var lastSendAudioData: Bool?
    var hasCapturedAudioData = true
    var prepareCallCount = 0
    var onStart: (() -> Void)?
    var startContinuation: CheckedContinuation<Void, Error>?

    func prepareRecordingPipelineIfAuthorized() async {
        prepareCallCount += 1
    }

    func setContextInfo(appName: String?, windowTitle: String?, taskCategory: String?) {}

    func startRecording(flowContext: String?) async throws {
        startCallCount += 1
        onStart?()
        try await withCheckedThrowingContinuation { continuation in
            startContinuation = continuation
        }
    }

    func cancelRecordingStartup() {
        cancelCallCount += 1
        startContinuation?.resume(throwing: CancellationError())
        startContinuation = nil
    }

    func stopRecording(sendAudioData: Bool, flowContext: String?, context: [String: Any]?) {
        stopCallCount += 1
        lastSendAudioData = sendAudioData
    }

    func completeStart() {
        startContinuation?.resume()
        startContinuation = nil
    }

    func failStart(_ error: Error) {
        startContinuation?.resume(throwing: error)
        startContinuation = nil
    }
}

@MainActor
final class TranscriptionRecordingLifecycleTests: XCTestCase {
    func makeViewModel(controller: MockTranscriptionAudioCaptureController) -> TranscriptionWidgetViewModel {
        let viewModel = TranscriptionWidgetViewModel(audioCaptureController: controller)
        viewModel.isConnected = true
        viewModel.isModelReady = true
        viewModel.transcriptionText = "Ready to record"
        return viewModel
    }

    func testStartRemainsStartingUntilAudioControllerCompletes() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        XCTAssertEqual(viewModel.recordingLifecycle, .starting)
        XCTAssertFalse(viewModel.isRecording)
        XCTAssertFalse(viewModel.isProcessingRecording)
        XCTAssertEqual(viewModel.transcriptionText, "Starting microphone...")

        controller.completeStart()
        await task.value
        XCTAssertEqual(viewModel.recordingLifecycle, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertEqual(controller.startCallCount, 1)
    }

    func testExplicitUserCancellationDuringStartupReturnsSilentlyToIdle() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        viewModel.cancelRecordingStartup()
        await task.value

        XCTAssertEqual(viewModel.recordingLifecycle, .idle)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(viewModel.transcriptionText, "Ready to record")
        XCTAssertEqual(controller.cancelCallCount, 1)
        XCTAssertEqual(controller.stopCallCount, 0)
    }

    func testCancellationClearsPendingAutoStartBeforeAudioStartup() {
        let controller = MockTranscriptionAudioCaptureController()
        let viewModel = makeViewModel(controller: controller)
        viewModel.pendingAutoStartRecording = true

        viewModel.cancelRecordingStartup()

        XCTAssertFalse(viewModel.pendingAutoStartRecording)
        XCTAssertFalse(viewModel.isStartingRecording)
        XCTAssertEqual(viewModel.recordingLifecycle, .idle)
        XCTAssertEqual(controller.cancelCallCount, 0)
    }

    func testDuplicateStartWhileStartingDoesNotLaunchSecondCapture() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let firstTask = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        await viewModel.startRecording()
        XCTAssertEqual(controller.startCallCount, 1)

        viewModel.cancelRecordingStartup()
        await firstTask.value
    }

    func testLateCompletionAfterCancellationCannotEnterRecording() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        viewModel.cancelRecordingStartup()
        controller.completeStart()
        await task.value

        XCTAssertEqual(viewModel.recordingLifecycle, .idle)
        XCTAssertFalse(viewModel.isRecording)
    }

    func testSuccessfulStopEntersProcessingAndSubmitsAudio() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value
        viewModel.stopRecording()

        XCTAssertEqual(viewModel.recordingLifecycle, .processing)
        XCTAssertTrue(viewModel.isProcessingRecording)
        XCTAssertFalse(viewModel.isRecording)
        XCTAssertEqual(controller.stopCallCount, 1)
        XCTAssertEqual(controller.lastSendAudioData, true)
    }

    func testStopWithoutCapturedAudioReturnsToRecoverableFailure() async {
        let controller = MockTranscriptionAudioCaptureController()
        controller.hasCapturedAudioData = false
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value
        viewModel.stopRecording()

        XCTAssertEqual(viewModel.recordingLifecycle, .failed)
        XCTAssertFalse(viewModel.isProcessingRecording)
        XCTAssertEqual(viewModel.error, "No audio was captured. Try recording again.")
        XCTAssertEqual(controller.stopCallCount, 1)
        XCTAssertEqual(controller.lastSendAudioData, false)
        XCTAssertTrue(viewModel.canToggleRecording)
    }

    func testStartupFailureEntersFailedState() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        controller.failStart(AudioCaptureError.configurationFailed("test failure"))
        await task.value

        XCTAssertEqual(viewModel.recordingLifecycle, .failed)
        XCTAssertFalse(viewModel.isRecording)
        XCTAssertFalse(viewModel.isProcessingRecording)
        XCTAssertNotNil(viewModel.error)
    }

    func testConnectedModelLoadingStillStartsMicrophoneCapture() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        viewModel.isModelReady = false
        viewModel.isModelLoading = true

        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value

        XCTAssertEqual(controller.startCallCount, 1)
        XCTAssertEqual(viewModel.recordingLifecycle, .recording)
        XCTAssertTrue(viewModel.isRecording)
    }

    func testRecordingAvailabilityAllowsConnectedModelLoadingOnlyUntilProcessing() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        viewModel.isModelReady = false
        viewModel.isModelLoading = true

        XCTAssertTrue(viewModel.canToggleRecording)

        let task = Task { await viewModel.startRecording() }
        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value
        viewModel.stopRecording()

        XCTAssertFalse(viewModel.canToggleRecording)
        viewModel.isConnected = false
        XCTAssertFalse(viewModel.canToggleRecording)
    }

    func testConnectionLossDuringProcessingReturnsToRecoverableFailure() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let viewModel = makeViewModel(controller: controller)
        let task = Task { await viewModel.startRecording() }

        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value
        viewModel.stopRecording()
        viewModel.isModelReady = true
        viewModel.isModelLoading = true
        viewModel.handleTranscriptionConnectionStateChange(false)

        XCTAssertEqual(viewModel.recordingLifecycle, .failed)
        XCTAssertFalse(viewModel.isProcessingRecording)
        XCTAssertFalse(viewModel.isModelReady)
        XCTAssertFalse(viewModel.isModelLoading)
        XCTAssertEqual(viewModel.error, "Connection lost before transcription completed.")
        XCTAssertEqual(viewModel.transcriptionText, "Disconnected from server...")
        XCTAssertFalse(viewModel.canToggleRecording)
    }

    func testInitialModelFailureKeepsAnEarlyRecordingControllable() async {
        let controller = MockTranscriptionAudioCaptureController()
        let started = expectation(description: "audio start entered")
        controller.onStart = { started.fulfill() }
        let webSocketService = WebSocketService.shared
        let viewModel = TranscriptionWidgetViewModel(
            webSocketService: webSocketService,
            audioCaptureController: controller
        )
        viewModel.setupSubscriptions()
        await Task.yield()
        viewModel.isConnected = true
        viewModel.isModelReady = false
        viewModel.isModelLoading = true

        let task = Task { await viewModel.startRecording() }
        await fulfillment(of: [started], timeout: 1.0)
        controller.completeStart()
        await task.value
        webSocketService.eventSubject.send(.transcriptionFailed("model initialization failed"))
        await Task.yield()

        XCTAssertEqual(viewModel.recordingLifecycle, .recording)
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertFalse(viewModel.isModelLoading)
        XCTAssertEqual(viewModel.error, "Error: model initialization failed")
        XCTAssertTrue(viewModel.canToggleRecording)

        viewModel.transitionRecordingLifecycle(to: .idle)
        viewModel.cancellables.removeAll()
        await Task.yield()
    }
}
