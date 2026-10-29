import XCTest
@testable import BasilClient

final class CaptureWindowControllerConfigurationTests: XCTestCase {
    @MainActor
    func testPreservesProvidedTaskIdAndUsesTextWindowSize() {
        let setup = AgentTaskCaptureInputWindowController.initialCaptureSetup(
            preGeneratedAgentTaskId: "task-123",
            modality: .text
        )

        XCTAssertEqual(setup.agentTaskId, "task-123")
        // Matches the archived `AgentTaskCaptureWidget.swift`'s text-mode
        // `minWidth: 280` / `dynamicHeight` base of 235 exactly.
        XCTAssertEqual(setup.windowSize, NSSize(width: 280, height: 235))
    }

    @MainActor
    func testGeneratesTaskIdAndUsesVoiceWindowSizeWhenNoIdIsProvided() {
        let setup = AgentTaskCaptureInputWindowController.initialCaptureSetup(
            preGeneratedAgentTaskId: nil,
            modality: .voice
        )

        XCTAssertFalse(setup.agentTaskId.isEmpty)
        // Matches the archived `AgentTaskCaptureWidget.swift`'s voice-mode
        // `minWidth/maxWidth: 160` / `dynamicHeight` base of 206 exactly.
        XCTAssertEqual(setup.windowSize, NSSize(width: 160, height: 206))
    }

    @MainActor
    func testNativeModelPickerPopoverUsesTranscriptMenuDimensions() {
        XCTAssertEqual(
            AgentTaskCaptureInputWindowController.nativeModelPickerPopoverContentSize(forModelCount: 1),
            NSSize(width: 210, height: 70)
        )
        XCTAssertEqual(
            AgentTaskCaptureInputWindowController.nativeModelPickerPopoverContentSize(forModelCount: 4),
            NSSize(width: 210, height: 146)
        )
        XCTAssertEqual(
            AgentTaskCaptureInputWindowController.nativeModelPickerPopoverContentSize(forModelCount: 100),
            NSSize(width: 210, height: 260)
        )
    }
}
