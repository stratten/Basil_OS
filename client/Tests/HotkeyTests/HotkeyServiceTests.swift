import XCTest
import HotKey
import Combine
import SwiftUI
@testable import BasilClient

// Mock AppDelegate for testing
@MainActor
class MockAppDelegate: NSObject, NSApplicationDelegate {
    var statusBarManager: HotkeyTestStatusBarManager?
    
    override init() {
        super.init()
        self.statusBarManager = HotkeyTestStatusBarManager()
    }
    
    func toggleTranscriptionWidget() {
        statusBarManager?.toggleTranscriptionWidget()
    }
}

// Create a struct that mimics the TranscriptionWidget but uses our mock view model
@MainActor
struct MockTranscriptionWidget: View {
    @ObservedObject var viewModel: MockTranscriptionViewModel
    
    var body: some View {
        Text("Mock Transcription Widget")
    }
}

// Mock StatusBarManager specifically for hotkey testing
@MainActor
class HotkeyTestStatusBarManager {
    var transcriptionWindow: NSWindow?
    var mockViewModel: MockTranscriptionViewModel?
    
    init() {
        mockViewModel = MockTranscriptionViewModel()
    }
    
    func toggleTranscriptionWidget() {
        if transcriptionWindow == nil {
            let window = NSWindow()
            // Create our mock widget with mock view model
            let widget = MockTranscriptionWidget(viewModel: mockViewModel!)
            window.contentView = NSHostingView(rootView: widget)
            transcriptionWindow = window
        } else {
            transcriptionWindow = nil
        }
    }
}

// Protocol that defines the requirements for a TranscriptionWidgetViewModel
// This avoids having to subclass the final class
@MainActor
protocol TranscriptionViewModelProtocol: ObservableObject {
    var isRecording: Bool { get set }
    func startRecording() async
    func stopRecording()
}

// Mock TranscriptionViewModel for testing
@MainActor
class MockTranscriptionViewModel: ObservableObject, TranscriptionViewModelProtocol {
    var recordingToggleCount = 0
    var startRecordingCount = 0
    var stopRecordingCount = 0
    @Published var isRecording: Bool = false
    @Published var isVisible: Bool = false
    @Published var isStartingRecording: Bool = false
    @Published var transcriptionText: String = ""
    @Published var error: String? = nil
    
    private var webSocketService: WebSocketService?
    
    init(webSocketService: WebSocketService? = nil) {
        self.webSocketService = webSocketService
    }
    
    var hotkeyRecordingState: TranscriptionHotkeyGestureState.ControllerState {
        if isStartingRecording { return .starting }
        if isRecording { return .recording }
        return .idle
    }

    func startRecording() async {
        startRecordingCount += 1
        isVisible = true
        isRecording = true
    }
    
    func stopRecording() {
        stopRecordingCount += 1
        isRecording = false
    }

    func cancelRecording() async {
        isStartingRecording = false
        isRecording = false
    }
}

extension MockTranscriptionViewModel: TranscriptionHotkeyControlling {}

@MainActor
class HotkeyServiceTests: XCTestCase {
    var hotkeyService: HotkeyService!
    var mockAppDelegate: MockAppDelegate!
    var cancellables: Set<AnyCancellable>!
    
    override func setUp() async throws {
        try await super.setUp()
        
        // Set up mock app delegate
        mockAppDelegate = MockAppDelegate()
        NSApplication.shared.delegate = mockAppDelegate
        
        hotkeyService = HotkeyService()
        hotkeyService.transcriptionControllerOverride = mockAppDelegate.statusBarManager?.mockViewModel
        cancellables = []
        
        // Enable hotkeys by default
        if !hotkeyService.isEnabled {
            hotkeyService.toggleHotkeys()
        }
    }
    
    override func tearDown() async throws {
        // Disable hotkeys
        if hotkeyService.isEnabled {
            hotkeyService.toggleHotkeys()
        }
        hotkeyService.transcriptionControllerOverride = nil
        
        hotkeyService = nil
        mockAppDelegate = nil
        cancellables = nil
        try await super.tearDown()
    }
    
    // MARK: - Hotkey Registration Tests
    
    func testHotkeyRegistrationWithDifferentKeys() async {
        // The legacy `capture_screen` and `get_suggestions` bindings (along
        // with their state-flag mirrors `isCaptureEnabled` /
        // `isSuggestionsEnabled`) were removed during the AssistantSession
        // unification. The post-unification surface registers
        // `transcribe_audio` here -- the suggestion- and agent_task-style
        // bindings have their own configuration paths and are exercised
        // in their respective integration tests.
        let testBindings: [String: HotkeyBinding] = [
            "transcribe_audio": HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        ]

        hotkeyService.configureHotkeys(with: testBindings)

        XCTAssertTrue(hotkeyService.isTranscriptionEnabled)
    }
    
    // MARK: - Transcription Toggle Tests
    
    func testTranscriptionHotkeyFirstPress() async {
        // Configure with test binding
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Verify initial state
        XCTAssertFalse(mockAppDelegate.statusBarManager?.mockViewModel?.isVisible ?? true)
        
        // Simulate hotkey press
        await hotkeyService.handleTranscriptionHotkey()
        
        // Verify the controller made the widget visible
        XCTAssertTrue(mockAppDelegate.statusBarManager?.mockViewModel?.isVisible ?? false)
        
        // Verify recording started
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertNotNil(viewModel)
        XCTAssertTrue(viewModel?.isRecording ?? false)
        XCTAssertEqual(viewModel?.startRecordingCount, 1)
    }
    
    func testTranscriptionHotkeyToggleBehavior() async {
        // Configure with test binding
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // First press - should create window and start recording
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertTrue(viewModel?.isRecording ?? false)
        
        // Second press - should stop recording
        await hotkeyService.handleTranscriptionHotkey()
        
        XCTAssertFalse(viewModel?.isRecording ?? true)
        XCTAssertEqual(viewModel?.stopRecordingCount, 1)
        
        // Third press - should start recording again
        await hotkeyService.handleTranscriptionHotkey()
        
        XCTAssertTrue(viewModel?.isRecording ?? false)
        XCTAssertEqual(viewModel?.startRecordingCount, 2)
    }
    
    func testRapidHotkeyPresses() async {
        // Configure with test binding
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Simulate rapid hotkey presses
        for i in 1...5 {
            print("Testing press #\(i)")
            if hotkeyService.shouldHandleHotkey() {
                await hotkeyService.handleTranscriptionHotkey()
            }
            // Simulate a very short delay between presses
            try? await Task.sleep(nanoseconds: 50_000_000) // 50ms
        }
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        
        // Due to debounce, we should see significantly fewer actual toggles than presses
        let totalToggleCount = (viewModel?.startRecordingCount ?? 0) + (viewModel?.stopRecordingCount ?? 0)
        XCTAssertLessThan(totalToggleCount, 5, "Debounce should prevent rapid toggles")
    }
    
    func testHotkeyPressWhileDisabled() async {
        // Configure hotkey but then disable
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        hotkeyService.toggleHotkeys() // Disable
        
        hotkeyService.disableAllHotkeys()

        XCTAssertFalse(hotkeyService.isTranscriptionEnabled)
        XCTAssertTrue(hotkeyService.hotkeys.isEmpty)
    }
    
    // MARK: - State Management Tests
    
    func testRecordingStateConsistency() async {
        // Configure hotkey
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Start recording
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertTrue(viewModel?.isRecording ?? false)
        
        // Simulate window close
        viewModel?.isVisible = false
        viewModel?.isRecording = false
        
        // Press hotkey again
        await hotkeyService.handleTranscriptionHotkey()
        
        // Should create new window and start fresh recording
        XCTAssertTrue(viewModel?.isVisible ?? false)
        XCTAssertTrue(viewModel?.isRecording ?? false)
    }
    
    func testHotkeyWithModifiers() async {
        // Configure hotkey with modifiers
        let binding = HotkeyBinding(key: "R", enabled: true, modifiers: ["cmd", "shift"])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Verify registration
        XCTAssertTrue(hotkeyService.isTranscriptionEnabled)
        
        // Test handling
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertTrue(viewModel?.isRecording ?? false)
    }
    
    // MARK: - Hotkey Registration Reliability Tests
    
    func testHotkeyAlwaysRegisters() async {
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        
        // Now press the hotkey 10 times with reasonable delays
        for i in 1...10 {
            print("Testing press #\(i)")
            await hotkeyService.handleTranscriptionHotkey()
            
            // Verify the press was handled
            if i % 2 == 0 {
                // Even presses should stop recording
                XCTAssertFalse(viewModel?.isRecording ?? true, "Press #\(i) failed to stop recording")
                XCTAssertEqual(viewModel?.stopRecordingCount, i/2, "Stop recording count incorrect after press #\(i)")
            } else {
                // Odd presses should start recording
                XCTAssertTrue(viewModel?.isRecording ?? false, "Press #\(i) failed to start recording")
                XCTAssertEqual(viewModel?.startRecordingCount, (i+1)/2, "Start recording count incorrect after press #\(i)")
            }
            
            // Add a realistic delay between presses
            try? await Task.sleep(nanoseconds: 500_000_000) // 500ms
        }
    }
    
    func testHotkeyRegistrationDuringRecording() async {
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Start recording
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertTrue(viewModel?.isRecording ?? false, "Failed to start initial recording")
        
        // Try to stop recording multiple times to ensure it always registers
        for i in 1...5 {
            print("Testing stop press #\(i)")
            await hotkeyService.handleTranscriptionHotkey()
            
            // Verify it stopped
            XCTAssertFalse(viewModel?.isRecording ?? true, "Failed to stop recording on press #\(i)")
            
            // Try to start again
            await hotkeyService.handleTranscriptionHotkey()
            XCTAssertTrue(viewModel?.isRecording ?? false, "Failed to restart recording after stop #\(i)")
        }
        
        // Verify total counts
        XCTAssertEqual(viewModel?.startRecordingCount, 6, "Incorrect number of recording starts")
        XCTAssertEqual(viewModel?.stopRecordingCount, 5, "Incorrect number of recording stops")
    }
    
    func testHotkeyRegistrationWithActiveWindow() async {
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Start recording
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        
        // Try to stop recording
        await hotkeyService.handleTranscriptionHotkey()
        
        // Verify it actually stopped
        XCTAssertFalse(viewModel?.isRecording ?? true, "Failed to stop recording with active window")
        XCTAssertEqual(viewModel?.stopRecordingCount, 1, "Stop recording not registered with active window")
        
        // Try to start again
        await hotkeyService.handleTranscriptionHotkey()
        
        // Verify it started
        XCTAssertTrue(viewModel?.isRecording ?? false, "Failed to start recording with active window")
        XCTAssertEqual(viewModel?.startRecordingCount, 2, "Start recording not registered with active window")
    }
    
    func testConsecutiveStopAttempts() async {
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        
        // Start recording
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertTrue(viewModel?.isRecording ?? false, "Failed to start recording")
        
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertFalse(viewModel?.isRecording ?? true, "Recording still active after stop")
        XCTAssertEqual(viewModel?.stopRecordingCount, 1, "Multiple stops registered when only one should be")
        
        // Verify we can start again
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertTrue(viewModel?.isRecording ?? false, "Failed to restart after multiple stop attempts")
    }
    
    func testHotkeyHandlingDuringActiveRecording() async {
        // Configure hotkey
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        // Start recording
        await hotkeyService.handleTranscriptionHotkey()
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertTrue(viewModel?.isRecording ?? false, "Recording should have started")
        
        // Simulate some time passing during recording
        try? await Task.sleep(nanoseconds: 1_000_000_000) // 1 second
        
        // Verify recording is still active
        XCTAssertTrue(viewModel?.isRecording ?? false, "Recording should still be active")
        
        // Try to stop recording with hotkey
        print("🔍 Attempting to stop recording with hotkey")
        await hotkeyService.handleTranscriptionHotkey()
        
        // Verify recording stopped
        XCTAssertFalse(viewModel?.isRecording ?? true, "Recording should have stopped")
        XCTAssertEqual(viewModel?.stopRecordingCount, 1, "Stop recording should have been called once")
        
        // Verify we can start recording again
        print("🔍 Attempting to start recording again")
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertTrue(viewModel?.isRecording ?? false, "Recording should have restarted")
        XCTAssertEqual(viewModel?.startRecordingCount, 2, "Start recording should have been called twice")
    }
    
    func testRecordingStateTransitions() async {
        // Configure hotkey
        let binding = HotkeyBinding(key: "F8", enabled: true, modifiers: [])
        hotkeyService.configureHotkeys(with: ["transcribe_audio": binding])
        
        let viewModel = mockAppDelegate.statusBarManager?.mockViewModel
        XCTAssertNotNil(viewModel, "ViewModel should exist")
        XCTAssertFalse(viewModel?.isRecording ?? true, "Should start in non-recording state")
        
        // Start recording
        print("🎯 Test: Starting recording")
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertTrue(viewModel?.isRecording ?? false, "Should be recording after first press")
        XCTAssertEqual(viewModel?.startRecordingCount, 1, "Start recording should be called once")
        
        // Small delay to simulate recording
        try? await Task.sleep(nanoseconds: 500_000_000) // 500ms
        
        // Stop recording
        print("🎯 Test: Stopping recording")
        await hotkeyService.handleTranscriptionHotkey()
        XCTAssertFalse(viewModel?.isRecording ?? true, "Should not be recording after second press")
        XCTAssertEqual(viewModel?.stopRecordingCount, 1, "Stop recording should be called once")
        
        // Verify state is consistent
        XCTAssertEqual(viewModel?.startRecordingCount, 1, "Start count should remain unchanged")
        XCTAssertEqual(viewModel?.stopRecordingCount, 1, "Stop count should remain unchanged")
    }

    func testActiveTranscriptionSuppressesSyntheticPasteHotkeysUntilCompletion() {
        hotkeyService.beginTranscriptionHotkeySuppression()

        XCTAssertFalse(hotkeyService.shouldHandleTranscriptionHotkey())

        hotkeyService.endTranscriptionHotkeySuppression()

        XCTAssertTrue(hotkeyService.shouldHandleTranscriptionHotkey())
    }
} 