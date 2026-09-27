import XCTest
@testable import BasilClient

final class TranscriptionHotkeyGestureStateTests: XCTestCase {
    func testQuickStartReleaseLeavesToggleRecordingActive() {
        var state = TranscriptionHotkeyGestureState()

        guard case .start = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected an idle press to start recording")
        }

        XCTAssertEqual(
            state.release(
                holdDuration: 0.2,
                threshold: 0.55,
                pushToTalkEnabled: true,
                controllerState: .starting
            ),
            .none
        )
    }

    func testHeldReleaseDuringStartupDefersStopForOwnedGesture() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let gestureID) = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected a start action")
        }

        XCTAssertEqual(
            state.release(
                holdDuration: 0.8,
                threshold: 0.55,
                pushToTalkEnabled: true,
                controllerState: .starting
            ),
            .deferStop(gestureID)
        )
        XCTAssertTrue(state.consumeDeferredStop(for: gestureID))
        XCTAssertFalse(state.consumeDeferredStop(for: gestureID))
    }

    func testHeldReleaseBeforeStartTaskRunsAlsoDefersStop() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let gestureID) = state.acceptPress(controllerState: .failed) else {
            return XCTFail("Expected a failed-state press to retry")
        }

        XCTAssertEqual(
            state.release(
                holdDuration: 1.0,
                threshold: 0.4,
                pushToTalkEnabled: true,
                controllerState: .idle
            ),
            .deferStop(gestureID)
        )
    }

    func testHeldReleaseAfterRecordingStartsStopsImmediately() {
        var state = TranscriptionHotkeyGestureState()
        _ = state.acceptPress(controllerState: .idle)

        XCTAssertEqual(
            state.release(
                holdDuration: 0.55,
                threshold: 0.55,
                pushToTalkEnabled: true,
                controllerState: .recording
            ),
            .stopRecording
        )
    }

    func testToggleStopReleaseIsInertEvenWhenHeld() {
        var state = TranscriptionHotkeyGestureState()

        XCTAssertEqual(state.acceptPress(controllerState: .recording), .stopRecording)
        XCTAssertEqual(
            state.release(
                holdDuration: 2.0,
                threshold: 0.2,
                pushToTalkEnabled: true,
                controllerState: .processing
            ),
            .none
        )
    }

    func testToggleCancelReleaseIsInertEvenWhenHeld() {
        var state = TranscriptionHotkeyGestureState()

        XCTAssertEqual(state.acceptPress(controllerState: .starting), .cancelStartup)
        XCTAssertEqual(
            state.release(
                holdDuration: 2.0,
                threshold: 0.2,
                pushToTalkEnabled: true,
                controllerState: .idle
            ),
            .none
        )
    }

    func testProcessingPressIsRejectedAndReleaseCannotStop() {
        var state = TranscriptionHotkeyGestureState()

        XCTAssertEqual(state.acceptPress(controllerState: .processing), .none)
        XCTAssertEqual(
            state.release(
                holdDuration: 1.0,
                threshold: 0.5,
                pushToTalkEnabled: true,
                controllerState: .recording
            ),
            .none
        )
    }

    func testDisabledPushToTalkLeavesRecordingActive() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let gestureID) = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected a start action")
        }

        XCTAssertEqual(
            state.release(
                holdDuration: 5.0,
                threshold: 0.1,
                pushToTalkEnabled: false,
                controllerState: .recording
            ),
            .none
        )
        XCTAssertFalse(state.consumeDeferredStop(for: gestureID))
    }

    func testConfiguredThresholdIsUsedAtBoundary() {
        var state = TranscriptionHotkeyGestureState()
        _ = state.acceptPress(controllerState: .idle)

        XCTAssertEqual(
            state.release(
                holdDuration: 0.875,
                threshold: 0.875,
                pushToTalkEnabled: true,
                controllerState: .recording
            ),
            .stopRecording
        )
    }

    func testNonDefaultThresholdRejectsShorterHold() {
        var state = TranscriptionHotkeyGestureState()
        _ = state.acceptPress(controllerState: .idle)

        XCTAssertEqual(
            state.release(
                holdDuration: 0.7,
                threshold: 0.875,
                pushToTalkEnabled: true,
                controllerState: .recording
            ),
            .none
        )
    }

    func testMismatchedGestureCannotConsumeDeferredStop() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let gestureID) = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected a start action")
        }
        _ = state.release(
            holdDuration: 1.0,
            threshold: 0.5,
            pushToTalkEnabled: true,
            controllerState: .starting
        )

        XCTAssertFalse(state.consumeDeferredStop(for: UUID()))
        XCTAssertTrue(state.consumeDeferredStop(for: gestureID))
    }

    func testNewAcceptedPressReplacesStaleGesture() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let staleID) = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected a start action")
        }
        _ = state.release(
            holdDuration: 1.0,
            threshold: 0.5,
            pushToTalkEnabled: true,
            controllerState: .starting
        )

        XCTAssertEqual(state.acceptPress(controllerState: .recording), .stopRecording)
        XCTAssertFalse(state.consumeDeferredStop(for: staleID))
    }

    func testResetClearsDeferredStop() {
        var state = TranscriptionHotkeyGestureState()
        guard case .start(let gestureID) = state.acceptPress(controllerState: .idle) else {
            return XCTFail("Expected a start action")
        }
        _ = state.release(
            holdDuration: 1.0,
            threshold: 0.5,
            pushToTalkEnabled: true,
            controllerState: .starting
        )

        state.reset()

        XCTAssertFalse(state.consumeDeferredStop(for: gestureID))
    }

    func testReleaseWithoutAcceptedPressMatchesDebouncedGesture() {
        var state = TranscriptionHotkeyGestureState()

        XCTAssertEqual(
            state.release(
                holdDuration: 1.0,
                threshold: 0.5,
                pushToTalkEnabled: true,
                controllerState: .recording
            ),
            .none
        )
    }
}
