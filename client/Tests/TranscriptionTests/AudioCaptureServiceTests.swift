import XCTest
import AVFoundation
import Combine
@testable import BasilClient

// Create a protocol to represent WebSocketService functionality with proper isolation
@MainActor
protocol WebSocketServiceProtocol {
    func sendAudioData(_ data: Data, forMeeting: Bool)
}

// Make the real WebSocketService conform to this protocol (extension in test target)
extension WebSocketService: WebSocketServiceProtocol {}

// Create a protocol to represent AudioCaptureService functionality
@MainActor
protocol AudioCaptureServiceProtocol {
    var isRecording: Bool { get }
    var error: String? { get }
    
    func startRecording(flowContext: String?) async throws
    func stopRecording(sendAudioData: Bool, flowContext: String?, context: [String: Any]?)
}

// Make AudioCaptureService conform to the protocol
extension AudioCaptureService: AudioCaptureServiceProtocol {}

// Create a mock that implements the protocol
@MainActor
final class MockWebSocketService: NSObject, WebSocketServiceProtocol {
    var sentAudioData: [Data] = []
    
    func sendAudioData(_ data: Data, forMeeting: Bool = false) {
        sentAudioData.append(data)
    }
}

// Test class to wrap AudioCaptureService for testing
@MainActor
final class TestAudioCaptureService {
    private let webSocketService: WebSocketServiceProtocol
    private let captureService: AudioCaptureService
    private var errorCancellable: AnyCancellable?
    private var errorSubject = PassthroughSubject<String?, Never>()
    
    init(webSocketService: WebSocketServiceProtocol) {
        self.webSocketService = webSocketService
        // We need to cast the mock to WebSocketService to satisfy the initializer
        // This is a limitation of the test environment - in a real app architecture,
        // we would use dependency injection to avoid this cast
        if let realService = webSocketService as? WebSocketService {
            self.captureService = AudioCaptureService(webSocketService: realService)
        } else {
            // In tests, we know the real service is never used, so we pass nil and inject our mock differently
            self.captureService = AudioCaptureService(webSocketService: nil)
            // TODO: Ideally, AudioCaptureService would accept a protocol type instead
        }
        
        // Set up error forwarding
        errorCancellable = captureService.$error.sink { [weak self] error in
            self?.errorSubject.send(error)
        }
    }
    
    var isRecording: Bool {
        return captureService.isRecording
    }
    
    var error: String? {
        return captureService.error
    }
    
    // Publisher for error changes
    var errorPublisher: AnyPublisher<String?, Never> {
        return errorSubject.eraseToAnyPublisher()
    }
    
    func startRecording(flowContext: String? = nil) async throws {
        try await captureService.startRecording(flowContext: flowContext)
    }
    
    func stopRecording(sendAudioData: Bool = true, flowContext: String? = nil, context: [String: Any]? = nil) {
        captureService.stopRecording(sendAudioData: sendAudioData, flowContext: flowContext, context: context)
    }
}

@MainActor
final class AudioCaptureServiceTests: XCTestCase {
    var captureService: TestAudioCaptureService!
    var mockWebSocket: MockWebSocketService!
    var cancellables: Set<AnyCancellable>!
    
    @MainActor
    override func setUp() async throws {
        try await super.setUp()
        mockWebSocket = MockWebSocketService()
        captureService = TestAudioCaptureService(webSocketService: mockWebSocket)
        cancellables = []
    }
    
    @MainActor
    override func tearDown() async throws {
        captureService.stopRecording() // No need for await here since it's not async
        captureService = nil
        mockWebSocket = nil
        cancellables = nil
        try await super.tearDown()
    }
    
    @MainActor
    func testRecordingStateManagement() async throws {
        // Initially not recording
        XCTAssertFalse(captureService.isRecording)
        
        // Start recording
        try await captureService.startRecording()
        XCTAssertTrue(captureService.isRecording)
        
        // Stop recording
        captureService.stopRecording() // No need for await here
        XCTAssertFalse(captureService.isRecording)
    }
    
    @MainActor
    func testErrorHandling() async throws {
        // Start recording once
        try await captureService.startRecording()
        
        // Second start should throw because capture is already active
        do {
            try await captureService.startRecording()
            XCTFail("Expected second startRecording call to throw")
        } catch {
            XCTAssertNotNil(error)
        }
        
        captureService.stopRecording()
    }
    
    @MainActor
    func testRecordingStateDuringCapture() async throws {
        // Start recording
        try await captureService.startRecording()
        
        // Wait a bit to collect some audio data
        try await Task.sleep(nanoseconds: 500_000_000) // 0.5 seconds
        
        XCTAssertTrue(captureService.isRecording)
        captureService.stopRecording()
        XCTAssertFalse(captureService.isRecording)
    }

    func testStoppedEngineConfigurationChangeCleansUpActiveRecording() {
        let service = AudioCaptureService(webSocketService: nil)
        service.isRecording = true
        let notification = Notification(
            name: .AVAudioEngineConfigurationChange,
            object: service.audioEngine
        )

        service.handleEngineConfigurationChange(notification)

        XCTAssertFalse(service.isRecording)
        XCTAssertEqual(service.error, "Microphone recording was interrupted.")
    }

    func testStartupEngineConfigurationChangeRecoversInsteadOfAborting() {
        let service = AudioCaptureService(webSocketService: nil)
        // Simulate an in-flight recording startup (suspended in
        // `waitForFirstCapturedBuffer`) rather than a steady-state recording.
        service.isRecording = true
        service.activeRecordingStartID = UUID()
        let notification = Notification(
            name: .AVAudioEngineConfigurationChange,
            object: service.audioEngine
        )

        service.handleEngineConfigurationChange(notification)

        // The transient settling configuration change that fires right after
        // `engine.start()` must not tear the recording down; recovery is
        // dispatched asynchronously instead. Assert synchronously before any
        // suspension so the dispatched recovery task cannot have run yet.
        XCTAssertTrue(service.isRecording)
        XCTAssertNil(service.error)
        XCTAssertNotNil(service.activeRecordingStartID)
    }

    func testFirstBufferSignalCompletesMatchingStartupOnlyOnce() async throws {
        let service = AudioCaptureService(webSocketService: nil)
        let startID = UUID()
        service.activeRecordingStartID = startID
        let waiter = Task {
            try await service.waitForFirstCapturedBuffer(startID: startID)
        }
        await Task.yield()

        service.signalFirstCapturedBuffer()
        service.signalFirstCapturedBuffer()

        try await waiter.value
        XCTAssertNil(service.firstBufferContinuation)
        XCTAssertNil(service.firstBufferStartID)
    }

    func testPipelineInvalidationClearsPreparedStateAndAdvancesGeneration() {
        let service = AudioCaptureService(webSocketService: nil)
        service.isAudioTapPrepared = true
        let originalGeneration = service.recordingPipelineGeneration

        service.invalidateRecordingPipelinePreparation()

        XCTAssertFalse(service.isAudioTapPrepared)
        XCTAssertEqual(service.recordingPipelineGeneration, originalGeneration + 1)
    }

    func testEngineOperationQueueDoesNotBlockMainActor() async {
        let operationQueue = AudioEngineOperationQueue()
        let queueStarted = expectation(description: "serial audio queue started")
        let releaseQueue = DispatchSemaphore(value: 0)
        let operation = Task {
            await operationQueue.runForTesting {
                queueStarted.fulfill()
                releaseQueue.wait()
            }
        }

        await fulfillment(of: [queueStarted], timeout: 1.0)
        var mainActorSentinelRan = false
        await MainActor.run {
            mainActorSentinelRan = true
        }

        XCTAssertTrue(mainActorSentinelRan)
        releaseQueue.signal()
        await operation.value
    }

    func testValidationSyntheticSourceCompletesFirstBufferWithoutHardwareInput() async throws {
        let fixtureURL = try makeSyntheticAudioFixture()
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }
        let source = ValidationSyntheticAudioCaptureSource(fixtureURL: fixtureURL)
        let service = AudioCaptureService(
            webSocketService: nil,
            validationSyntheticAudioSource: source
        )

        XCTAssertTrue(service.permissionGranted)
        XCTAssertNil(service.audioEngine)

        try await service.startRecording(flowContext: "transcription")

        XCTAssertTrue(service.isRecording)
        XCTAssertGreaterThan(service.recordingData.count, 0)
        XCTAssertNil(service.activeRecordingStartID)

        service.stopRecording(sendAudioData: false)

        XCTAssertFalse(service.isRecording)
        XCTAssertNil(source.playbackTask)
    }

    func testNormalCaptureExplicitlyExcludesValidationSyntheticSource() {
        let service = AudioCaptureService(
            webSocketService: nil,
            validationSyntheticAudioSource: nil
        )

        XCTAssertNil(service.validationSyntheticAudioSource)
        XCTAssertNotNil(service.audioEngine)
    }

    func testValidationSyntheticSourceRapidRestartRetainsCurrentPlayback() async throws {
        let fixtureURL = try makeSyntheticAudioFixture()
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }
        let source = ValidationSyntheticAudioCaptureSource(fixtureURL: fixtureURL)
        let service = AudioCaptureService(
            webSocketService: nil,
            validationSyntheticAudioSource: source
        )

        try await service.startRecording(flowContext: "transcription")
        service.stopRecording(sendAudioData: false)
        try await service.startRecording(flowContext: "transcription")
        await Task.yield()

        XCTAssertTrue(service.isRecording)
        XCTAssertNotNil(source.playbackTask)
        XCTAssertGreaterThan(service.recordingData.count, 0)

        service.stopRecording(sendAudioData: false)
        XCTAssertNil(source.playbackTask)
    }

    func testRecordingAdmissionAllowsOnlyOneServiceAtATime() throws {
        let transcription = AudioCaptureService(webSocketService: nil)
        let agentTask = AudioCaptureService(webSocketService: nil)
        defer {
            transcription.markRecordingInactive()
            agentTask.markRecordingInactive()
        }

        try transcription.reserveRecordingAdmission(flowContext: "transcription")

        XCTAssertThrowsError(try agentTask.reserveRecordingAdmission(flowContext: "agentTask"))
        XCTAssertEqual(AudioCaptureService.blockingRecordingOwners(), ["transcription"])

        transcription.markRecordingInactive()

        XCTAssertNoThrow(try agentTask.reserveRecordingAdmission(flowContext: "agentTask"))
        XCTAssertEqual(AudioCaptureService.blockingRecordingOwners(), ["agentTask"])
    }

    private func makeSyntheticAudioFixture() throws -> URL {
        let directoryURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directoryURL,
            withIntermediateDirectories: true
        )
        let fixtureURL = directoryURL.appendingPathComponent("fixture.wav")
        let format = try XCTUnwrap(
            AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: 16_000,
                channels: 1,
                interleaved: false
            )
        )
        let frameCount: AVAudioFrameCount = 4_096
        let buffer = try XCTUnwrap(
            AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount)
        )
        buffer.frameLength = frameCount
        let samples = try XCTUnwrap(buffer.floatChannelData?[0])
        for index in 0..<Int(frameCount) {
            samples[index] = sin(Float(index) * 2 * .pi * 440 / 16_000) * 0.25
        }
        let file = try AVAudioFile(
            forWriting: fixtureURL,
            settings: format.settings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
        try file.write(from: buffer)
        return fixtureURL
    }
} 