import XCTest
@testable import BasilClient

final class CaptureBackendAcknowledgmentTests: XCTestCase {
    private let origin = Date(timeIntervalSince1970: 1_000)

    func testConsumeWithoutBeginIsFalse() {
        var gate = AgentTaskCaptureAcknowledgmentGate()

        XCTAssertFalse(gate.consume(now: origin))
        XCTAssertFalse(gate.isAwaiting)
    }

    func testConsumeIsOneShot() {
        var gate = AgentTaskCaptureAcknowledgmentGate()
        gate.begin(now: origin)

        XCTAssertTrue(gate.isAwaiting)
        XCTAssertTrue(gate.consume(now: origin.addingTimeInterval(0.4)))
        XCTAssertFalse(gate.consume(now: origin.addingTimeInterval(0.5)))
        XCTAssertFalse(gate.isAwaiting)
    }

    func testConsumeAfterDeadlineIsFalseAndDisarms() {
        var gate = AgentTaskCaptureAcknowledgmentGate()
        gate.begin(now: origin)

        let late = origin.addingTimeInterval(AgentTaskCaptureAcknowledgmentGate.timeoutSeconds + 0.001)
        XCTAssertFalse(gate.consume(now: late))
        XCTAssertFalse(gate.isAwaiting)
    }

    func testConsumeExactlyAtDeadlineIsTrue() {
        var gate = AgentTaskCaptureAcknowledgmentGate()
        gate.begin(now: origin)

        let boundary = origin.addingTimeInterval(AgentTaskCaptureAcknowledgmentGate.timeoutSeconds)
        XCTAssertTrue(gate.consume(now: boundary))
    }

    func testBeginRearmsAfterConsume() {
        var gate = AgentTaskCaptureAcknowledgmentGate()
        gate.begin(now: origin)
        XCTAssertTrue(gate.consume(now: origin))

        gate.begin(now: origin.addingTimeInterval(60))
        XCTAssertTrue(gate.consume(now: origin.addingTimeInterval(61)))
    }

    func testBackendAcceptedWakeWordReadsTheFlag() {
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data(#"{"success":true,"accepted":true}"#.utf8)))
        XCTAssertFalse(HotkeyService.backendAcceptedWakeWord(Data(#"{"success":true,"accepted":false}"#.utf8)))
    }

    func testBackendAcceptedWakeWordDefaultsToAcceptedForOlderBackends() {
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data(#"{"success":true}"#.utf8)))
    }

    func testBackendAcceptedWakeWordDefaultsToAcceptedForMalformedBodies() {
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data()))
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data("not json".utf8)))
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data("[1,2]".utf8)))
        XCTAssertTrue(HotkeyService.backendAcceptedWakeWord(Data(#"{"accepted":"no"}"#.utf8)))
    }

    @MainActor
    func testDismissWithoutAPanelDisarmsTheGateAndDoesNothingElse() {
        let controller = AgentTaskCaptureInputWindowController()
        controller.beginAwaitingBackendAcknowledgment(now: origin)
        XCTAssertTrue(controller.backendAcknowledgmentGate.isAwaiting)

        controller.dismissAfterBackendRejection(now: origin.addingTimeInterval(1))

        XCTAssertFalse(controller.backendAcknowledgmentGate.isAwaiting)
        XCTAssertFalse(controller.isVisible)
    }

    @MainActor
    func testDismissAfterTheAcknowledgmentArrivedIsANoOp() {
        let controller = AgentTaskCaptureInputWindowController()
        controller.beginAwaitingBackendAcknowledgment(now: origin)
        XCTAssertTrue(controller.backendAcknowledgmentGate.consume(now: origin.addingTimeInterval(0.3)))

        controller.dismissAfterBackendRejection(now: origin.addingTimeInterval(0.6))

        XCTAssertFalse(controller.backendAcknowledgmentGate.isAwaiting)
    }

    @MainActor
    func testStaticConsumeIsFalseWhenTheActiveControllerWasNeverArmed() {
        XCTAssertFalse(AgentTaskCaptureInputWindowController.consumeBackendAcknowledgment(now: origin))
    }
}
